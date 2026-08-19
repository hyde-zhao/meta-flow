"""0.6.1 单一发布 lineage 的顺序、计数、授权与恢复合同。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from meta_flow.state.projection_transaction import (
    atomic_replace_bytes,
    ensure_transaction_directory,
)
from meta_flow.workflow.package_plan import canonical_digest, canonical_json

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

RELEASE_STATES = (
    "work-verified",
    "source-candidate-ready",
    "source-frozen",
    "version-decided",
    "fingerprinted",
    "provider-qualified",
    "artifacts-built",
    "canary-passed",
    "cp8-approved",
    "released",
)

_ACTION_TRANSITIONS = {
    "candidate-ready": ("work-verified", "source-candidate-ready"),
    "freeze-source": ("source-candidate-ready", "source-frozen"),
    "decide-version": ("source-frozen", "version-decided"),
    "fingerprint": ("version-decided", "fingerprinted"),
    "qualify-provider-source": ("fingerprinted", "provider-qualified"),
    "build-artifacts": ("provider-qualified", "artifacts-built"),
    "pass-canary": ("artifacts-built", "canary-passed"),
    "approve-cp8": ("canary-passed", "cp8-approved"),
    "release": ("cp8-approved", "released"),
}

ACTION_COUNT_KEYS = (
    "version-metadata-change",
    "source-freeze",
    "version-decision",
    "fingerprint",
    "provider-qualification",
    "artifact-build",
    "artifact-materialization",
    "canary",
    "cp8",
    "release",
    "intermediate-release",
)

_ACTION_COUNTERS = {
    "candidate-ready": ("version-metadata-change",),
    "freeze-source": ("source-freeze",),
    "decide-version": ("version-decision",),
    "fingerprint": ("fingerprint",),
    "qualify-provider-source": ("provider-qualification",),
    "build-artifacts": ("artifact-build", "artifact-materialization"),
    "pass-canary": ("canary",),
    "approve-cp8": ("cp8",),
    "release": ("release",),
}


def _closed(value: object, fields: set[str], *, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(code)
    return value


def _text(
    value: object,
    *,
    code: str,
    pattern: re.Pattern[str] | None = None,
    allow_empty: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or (not value and not allow_empty)
        or (pattern is not None and not pattern.fullmatch(value))
    ):
        raise ValueError(code)
    return value


def _strings(value: object, *, code: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item or item != item.strip() for item in value
    ):
        raise ValueError(code)
    return tuple(sorted(set(value)))


def _safe_ref(value: object, *, code: str) -> str:
    ref = _text(value, code=code)
    if (
        ref.startswith("/")
        or "\\" in ref
        or "://" in ref
        or any(part in {"", ".", ".."} for part in ref.split("/"))
    ):
        raise ValueError(code)
    return ref


def _count_mapping(value: object) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, Mapping) or set(value) != set(ACTION_COUNT_KEYS):
        raise ValueError("RELEASE_ACTION_COUNTS_INVALID")
    result: list[tuple[str, int]] = []
    for key in ACTION_COUNT_KEYS:
        count = value[key]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("RELEASE_ACTION_COUNTS_INVALID")
        result.append((key, count))
    return tuple(result)


def _counts_dict(value: Sequence[tuple[str, int]]) -> dict[str, int]:
    return {key: count for key, count in value}


def _parse_timestamp(value: str, *, code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(code) from exc
    if parsed.tzinfo is None:
        raise ValueError(code)
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class ReleaseEventRecordV1:
    event_id: str
    action: str
    event_digest: str
    transition_key: str

    @classmethod
    def from_mapping(cls, value: object) -> ReleaseEventRecordV1:
        item = _closed(
            value,
            {"event_id", "action", "event_digest", "transition_key"},
            code="RELEASE_EVENT_RECORD_FIELDS_MISMATCH",
        )
        action = _text(item["action"], code="RELEASE_ACTION_INVALID")
        if action not in _ACTION_TRANSITIONS:
            raise ValueError("RELEASE_ACTION_INVALID")
        return cls(
            event_id=_text(item["event_id"], code="RELEASE_EVENT_ID_INVALID", pattern=_ID_RE),
            action=action,
            event_digest=_text(
                item["event_digest"], code="RELEASE_EVENT_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            transition_key=_text(
                item["transition_key"], code="RELEASE_TRANSITION_KEY_INVALID", pattern=_DIGEST_RE
            ),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "action": self.action,
            "event_digest": self.event_digest,
            "transition_key": self.transition_key,
        }


@dataclass(frozen=True)
class AggregateReleaseStateV1:
    schema_version: int
    package_id: str
    cr_id: str
    version: str
    current_state: str
    source_fingerprint: str
    plan_digest: str
    cost_digest: str
    compatibility_digest: str
    predecessor_receipt_digest: str
    work_verification_digests: tuple[str, ...]
    action_counts: tuple[tuple[str, int], ...]
    event_records: tuple[ReleaseEventRecordV1, ...]
    consumed_bootstrap_keys: tuple[str, ...]
    invalidations: tuple[str, ...]
    state_digest: str

    @classmethod
    def from_mapping(cls, value: object) -> AggregateReleaseStateV1:
        fields = {
            "schema_version",
            "kind",
            "package_id",
            "cr_id",
            "version",
            "current_state",
            "source_fingerprint",
            "plan_digest",
            "cost_digest",
            "compatibility_digest",
            "predecessor_receipt_digest",
            "work_verification_digests",
            "action_counts",
            "event_records",
            "consumed_bootstrap_keys",
            "invalidations",
            "state_digest",
        }
        item = _closed(value, fields, code="RELEASE_STATE_FIELDS_MISMATCH")
        if item["schema_version"] != 1 or item["kind"] != "AggregateReleaseStateV1":
            raise ValueError("RELEASE_STATE_SCHEMA_INVALID")
        current_state = _text(item["current_state"], code="RELEASE_STATE_INVALID")
        if current_state not in RELEASE_STATES:
            raise ValueError("RELEASE_STATE_INVALID")
        if not isinstance(item["event_records"], (list, tuple)):
            raise ValueError("RELEASE_EVENT_RECORDS_INVALID")
        state = cls(
            schema_version=1,
            package_id=_text(item["package_id"], code="RELEASE_PACKAGE_ID_INVALID", pattern=_ID_RE),
            cr_id=_text(item["cr_id"], code="RELEASE_CR_ID_INVALID", pattern=_ID_RE),
            version=_text(item["version"], code="RELEASE_VERSION_INVALID", pattern=_VERSION_RE),
            current_state=current_state,
            source_fingerprint=_text(
                item["source_fingerprint"], code="RELEASE_BINDING_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            plan_digest=_text(
                item["plan_digest"], code="RELEASE_BINDING_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            cost_digest=_text(
                item["cost_digest"], code="RELEASE_BINDING_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            compatibility_digest=_text(
                item["compatibility_digest"],
                code="RELEASE_BINDING_DIGEST_INVALID",
                pattern=_DIGEST_RE,
            ),
            predecessor_receipt_digest=_text(
                item["predecessor_receipt_digest"],
                code="RELEASE_PREDECESSOR_DIGEST_INVALID",
                pattern=_DIGEST_RE,
            ),
            work_verification_digests=_strings(
                item["work_verification_digests"], code="RELEASE_WORK_EVIDENCE_INVALID"
            ),
            action_counts=_count_mapping(item["action_counts"]),
            event_records=tuple(
                ReleaseEventRecordV1.from_mapping(record) for record in item["event_records"]
            ),
            consumed_bootstrap_keys=_strings(
                item["consumed_bootstrap_keys"], code="RELEASE_BOOTSTRAP_HISTORY_INVALID"
            ),
            invalidations=_strings(item["invalidations"], code="RELEASE_INVALIDATIONS_INVALID"),
            state_digest=_text(
                item["state_digest"], code="RELEASE_STATE_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
        )
        if state.state_digest != canonical_digest(state._payload()):
            raise ValueError("RELEASE_STATE_DIGEST_MISMATCH")
        return state

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": "AggregateReleaseStateV1",
            "package_id": self.package_id,
            "cr_id": self.cr_id,
            "version": self.version,
            "current_state": self.current_state,
            "source_fingerprint": self.source_fingerprint,
            "plan_digest": self.plan_digest,
            "cost_digest": self.cost_digest,
            "compatibility_digest": self.compatibility_digest,
            "predecessor_receipt_digest": self.predecessor_receipt_digest,
            "work_verification_digests": list(self.work_verification_digests),
            "action_counts": _counts_dict(self.action_counts),
            "event_records": [item.as_dict() for item in self.event_records],
            "consumed_bootstrap_keys": list(self.consumed_bootstrap_keys),
            "invalidations": list(self.invalidations),
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self._payload(), "state_digest": self.state_digest}


def build_initial_release_state(
    *,
    package_id: str,
    cr_id: str,
    version: str,
    source_fingerprint: str,
    plan_digest: str,
    cost_digest: str,
    compatibility_digest: str,
    work_verification_digests: Sequence[str],
    predecessor_receipt_digest: str,
) -> AggregateReleaseStateV1:
    payload = {
        "schema_version": 1,
        "kind": "AggregateReleaseStateV1",
        "package_id": package_id,
        "cr_id": cr_id,
        "version": version,
        "current_state": "work-verified",
        "source_fingerprint": source_fingerprint,
        "plan_digest": plan_digest,
        "cost_digest": cost_digest,
        "compatibility_digest": compatibility_digest,
        "predecessor_receipt_digest": predecessor_receipt_digest,
        "work_verification_digests": sorted(set(work_verification_digests)),
        "action_counts": {key: 0 for key in ACTION_COUNT_KEYS},
        "event_records": [],
        "consumed_bootstrap_keys": [],
        "invalidations": [],
    }
    payload["state_digest"] = canonical_digest(payload)
    return AggregateReleaseStateV1.from_mapping(payload)


@dataclass(frozen=True)
class ReleaseEventV1:
    schema_version: int
    event_id: str
    action: str
    target_state: str
    package_id: str
    cr_id: str
    version: str
    predecessor_receipt_digest: str
    source_fingerprint: str
    plan_digest: str
    cost_digest: str
    compatibility_digest: str
    evidence_ref: str
    evidence_digest: str
    execution_class: str
    reservation_id: str
    attempt_id: str
    bootstrap_consumption_key: str
    source_qualification_receipt_digest: str
    wheel_build_count: int
    qualification_increment: int
    materialization_count: int
    intermediate_release_count: int
    harness_error_count: int
    asset_digests: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: object) -> ReleaseEventV1:
        fields = {
            "schema_version",
            "event_id",
            "action",
            "target_state",
            "package_id",
            "cr_id",
            "version",
            "predecessor_receipt_digest",
            "source_fingerprint",
            "plan_digest",
            "cost_digest",
            "compatibility_digest",
            "evidence_ref",
            "evidence_digest",
            "execution_class",
            "reservation_id",
            "attempt_id",
            "bootstrap_consumption_key",
            "source_qualification_receipt_digest",
            "wheel_build_count",
            "qualification_increment",
            "materialization_count",
            "intermediate_release_count",
            "harness_error_count",
            "asset_digests",
        }
        item = _closed(value, fields, code="RELEASE_EVENT_FIELDS_MISMATCH")
        if item["schema_version"] != 1:
            raise ValueError("RELEASE_EVENT_SCHEMA_INVALID")
        action = _text(item["action"], code="RELEASE_ACTION_INVALID")
        if action not in _ACTION_TRANSITIONS:
            raise ValueError("RELEASE_ACTION_INVALID")
        execution_class = _text(item["execution_class"], code="RELEASE_EXECUTION_CLASS_INVALID")
        if execution_class not in {"governance-transition", "release-action", "dry-run", "fixture"}:
            raise ValueError("RELEASE_EXECUTION_CLASS_INVALID")
        numeric: dict[str, int] = {}
        for field in (
            "wheel_build_count",
            "qualification_increment",
            "materialization_count",
            "intermediate_release_count",
            "harness_error_count",
        ):
            count = item[field]
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("RELEASE_EVENT_COUNT_INVALID")
            numeric[field] = count
        return cls(
            schema_version=1,
            event_id=_text(item["event_id"], code="RELEASE_EVENT_ID_INVALID", pattern=_ID_RE),
            action=action,
            target_state=_text(item["target_state"], code="RELEASE_TARGET_STATE_INVALID"),
            package_id=_text(item["package_id"], code="RELEASE_PACKAGE_ID_INVALID", pattern=_ID_RE),
            cr_id=_text(item["cr_id"], code="RELEASE_CR_ID_INVALID", pattern=_ID_RE),
            version=_text(item["version"], code="RELEASE_VERSION_INVALID", pattern=_VERSION_RE),
            predecessor_receipt_digest=_text(
                item["predecessor_receipt_digest"],
                code="RELEASE_PREDECESSOR_DIGEST_INVALID",
                pattern=_DIGEST_RE,
            ),
            source_fingerprint=_text(
                item["source_fingerprint"], code="RELEASE_BINDING_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            plan_digest=_text(
                item["plan_digest"], code="RELEASE_BINDING_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            cost_digest=_text(
                item["cost_digest"], code="RELEASE_BINDING_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            compatibility_digest=_text(
                item["compatibility_digest"],
                code="RELEASE_BINDING_DIGEST_INVALID",
                pattern=_DIGEST_RE,
            ),
            evidence_ref=_safe_ref(item["evidence_ref"], code="RELEASE_EVIDENCE_REF_INVALID"),
            evidence_digest=_text(
                item["evidence_digest"], code="RELEASE_EVIDENCE_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            execution_class=execution_class,
            reservation_id=_text(
                item["reservation_id"], code="RELEASE_RESERVATION_ID_INVALID", allow_empty=True
            ),
            attempt_id=_text(
                item["attempt_id"], code="RELEASE_ATTEMPT_ID_INVALID", allow_empty=True
            ),
            bootstrap_consumption_key=_text(
                item["bootstrap_consumption_key"],
                code="RELEASE_BOOTSTRAP_KEY_INVALID",
                pattern=_DIGEST_RE if item["bootstrap_consumption_key"] else None,
                allow_empty=True,
            ),
            source_qualification_receipt_digest=_text(
                item["source_qualification_receipt_digest"],
                code="RELEASE_SOURCE_QUALIFICATION_DIGEST_INVALID",
                pattern=_DIGEST_RE if item["source_qualification_receipt_digest"] else None,
                allow_empty=True,
            ),
            wheel_build_count=numeric["wheel_build_count"],
            qualification_increment=numeric["qualification_increment"],
            materialization_count=numeric["materialization_count"],
            intermediate_release_count=numeric["intermediate_release_count"],
            harness_error_count=numeric["harness_error_count"],
            asset_digests=_strings(item["asset_digests"], code="RELEASE_ASSET_DIGESTS_INVALID"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "action": self.action,
            "target_state": self.target_state,
            "package_id": self.package_id,
            "cr_id": self.cr_id,
            "version": self.version,
            "predecessor_receipt_digest": self.predecessor_receipt_digest,
            "source_fingerprint": self.source_fingerprint,
            "plan_digest": self.plan_digest,
            "cost_digest": self.cost_digest,
            "compatibility_digest": self.compatibility_digest,
            "evidence_ref": self.evidence_ref,
            "evidence_digest": self.evidence_digest,
            "execution_class": self.execution_class,
            "reservation_id": self.reservation_id,
            "attempt_id": self.attempt_id,
            "bootstrap_consumption_key": self.bootstrap_consumption_key,
            "source_qualification_receipt_digest": self.source_qualification_receipt_digest,
            "wheel_build_count": self.wheel_build_count,
            "qualification_increment": self.qualification_increment,
            "materialization_count": self.materialization_count,
            "intermediate_release_count": self.intermediate_release_count,
            "harness_error_count": self.harness_error_count,
            "asset_digests": list(self.asset_digests),
        }

    @property
    def event_digest(self) -> str:
        return canonical_digest(self.as_dict())


@dataclass(frozen=True)
class ReleaseSnapshotV1:
    schema_version: int
    state_digest: str
    source_fingerprint: str
    plan_digest: str
    cost_digest: str
    compatibility_digest: str
    dirty_inventory_digest: str
    ledger_preimage_digest: str
    projection_preimage_digest: str
    journal_status: str

    @classmethod
    def from_mapping(cls, value: object) -> ReleaseSnapshotV1:
        fields = {
            "schema_version",
            "state_digest",
            "source_fingerprint",
            "plan_digest",
            "cost_digest",
            "compatibility_digest",
            "dirty_inventory_digest",
            "ledger_preimage_digest",
            "projection_preimage_digest",
            "journal_status",
        }
        item = _closed(value, fields, code="RELEASE_SNAPSHOT_FIELDS_MISMATCH")
        if item["schema_version"] != 1:
            raise ValueError("RELEASE_SNAPSHOT_SCHEMA_INVALID")
        status = _text(item["journal_status"], code="RELEASE_JOURNAL_STATUS_INVALID")
        if status not in {"clean", "partial", "recovered"}:
            raise ValueError("RELEASE_JOURNAL_STATUS_INVALID")
        digests = {}
        for field in fields - {"schema_version", "journal_status"}:
            digests[field] = _text(
                item[field], code="RELEASE_SNAPSHOT_DIGEST_INVALID", pattern=_DIGEST_RE
            )
        return cls(schema_version=1, journal_status=status, **digests)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state_digest": self.state_digest,
            "source_fingerprint": self.source_fingerprint,
            "plan_digest": self.plan_digest,
            "cost_digest": self.cost_digest,
            "compatibility_digest": self.compatibility_digest,
            "dirty_inventory_digest": self.dirty_inventory_digest,
            "ledger_preimage_digest": self.ledger_preimage_digest,
            "projection_preimage_digest": self.projection_preimage_digest,
            "journal_status": self.journal_status,
        }

    @property
    def snapshot_digest(self) -> str:
        return canonical_digest(self.as_dict())


@dataclass(frozen=True)
class ReleaseDiagnosticV1:
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": "BLOCKER", "code": self.code, "message": self.message}


@dataclass(frozen=True)
class ReleaseCheckResultV1:
    decision: str
    diagnostics: tuple[ReleaseDiagnosticV1, ...]
    event_digest: str
    mutation_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "ReleaseCheckResultV1",
            "decision": self.decision,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "event_digest": self.event_digest,
            "mutation_count": self.mutation_count,
        }


def _diagnostic(code: str, message: str) -> ReleaseDiagnosticV1:
    return ReleaseDiagnosticV1(code, message)


def check_release_transition(
    state: AggregateReleaseStateV1, event: ReleaseEventV1
) -> ReleaseCheckResultV1:
    diagnostics: list[ReleaseDiagnosticV1] = []
    existing = [item for item in state.event_records if item.event_id == event.event_id]
    if existing:
        decision = "NO_CHANGE" if len(existing) == 1 and existing[0].event_digest == event.event_digest else "BLOCKED"
        if decision == "BLOCKED":
            diagnostics.append(
                _diagnostic("RELEASE_EVENT_CONFLICT", "event identity already binds different evidence")
            )
        return ReleaseCheckResultV1(decision, tuple(diagnostics), event.event_digest)

    if (state.package_id, state.cr_id, state.version) != (
        event.package_id,
        event.cr_id,
        event.version,
    ):
        diagnostics.append(_diagnostic("RELEASE_IDENTITY_MISMATCH", "package/CR/version differs"))
    expected_from, expected_to = _ACTION_TRANSITIONS[event.action]
    if event.action == "release" and state.current_state != "cp8-approved":
        diagnostics.append(
            _diagnostic(
                "INTERMEDIATE_RELEASE_FORBIDDEN",
                "release is admitted only after aggregate CP8 approval",
            )
        )
    elif state.current_state != expected_from or event.target_state != expected_to:
        diagnostics.append(
            _diagnostic(
                "RELEASE_ORDER_VIOLATION",
                f"{event.action} requires {expected_from}->{expected_to}",
            )
        )
    if event.predecessor_receipt_digest != state.predecessor_receipt_digest:
        diagnostics.append(
            _diagnostic("RELEASE_PREDECESSOR_STALE", "predecessor receipt digest differs")
        )
    if (
        event.source_fingerprint != state.source_fingerprint
        or event.plan_digest != state.plan_digest
        or event.cost_digest != state.cost_digest
        or event.compatibility_digest != state.compatibility_digest
    ):
        diagnostics.append(_diagnostic("RELEASE_BINDING_DRIFT", "source/Plan/cost/compat binding drift"))
    if len(state.work_verification_digests) != 2:
        diagnostics.append(
            _diagnostic(
                "INTERMEDIATE_RELEASE_FORBIDDEN",
                "one aggregate package requires exactly two verified Work receipts",
            )
        )
    if state.invalidations:
        diagnostics.append(_diagnostic("RELEASE_LINEAGE_INVALIDATED", "lineage has invalidations"))
    if event.execution_class in {"dry-run", "fixture"}:
        diagnostics.append(
            _diagnostic(
                "SIMULATED_EVIDENCE_NON_AUTHORITATIVE",
                "dry-run or fixture evidence cannot advance release truth",
            )
        )
    counts = _counts_dict(state.action_counts)
    for counter in _ACTION_COUNTERS[event.action]:
        if counts[counter] >= 1:
            diagnostics.append(
                _diagnostic(
                    f"{counter.upper().replace('-', '_')}_COUNT_EXCEEDED",
                    f"{counter} already has an attempt in canonical history",
                )
            )
    if event.intermediate_release_count != 0 or counts["intermediate-release"] != 0:
        diagnostics.append(
            _diagnostic("INTERMEDIATE_RELEASE_FORBIDDEN", "intermediate release count must stay zero")
        )
    counted = bool(_ACTION_COUNTERS[event.action])
    if counted and (not event.reservation_id or not event.attempt_id):
        diagnostics.append(
            _diagnostic("RELEASE_RESERVATION_REQUIRED", "counted action requires reservation and attempt IDs")
        )
    if event.action == "decide-version":
        if not event.bootstrap_consumption_key:
            diagnostics.append(
                _diagnostic("SEMVER_BOOTSTRAP_REQUIRED", "0.6.1 decision must consume one bootstrap key")
            )
        elif event.bootstrap_consumption_key in state.consumed_bootstrap_keys:
            diagnostics.append(
                _diagnostic("BOOTSTRAP_ALREADY_CONSUMED", "bootstrap key is already consumed")
            )
    elif event.bootstrap_consumption_key:
        diagnostics.append(
            _diagnostic("SEMVER_BOOTSTRAP_ACTION_MISMATCH", "only decide-version may consume bootstrap")
        )
    if event.action == "qualify-provider-source":
        if event.wheel_build_count != 0 or event.qualification_increment != 1:
            diagnostics.append(
                _diagnostic(
                    "SOURCE_QUALIFICATION_HIDDEN_BUILD",
                    "source qualification requires wheel_build_count=0 and qualification_increment=1",
                )
            )
    elif event.action == "build-artifacts":
        if (
            not event.source_qualification_receipt_digest
            or
            event.wheel_build_count != 1
            or event.qualification_increment != 0
            or event.materialization_count != 1
            or len(event.asset_digests) != 4
        ):
            diagnostics.append(
                _diagnostic(
                    "ARTIFACT_MATERIALIZATION_CONTRACT_INVALID",
                    "build requires source qualification, one build, four assets, one materialization and no qualification increment",
                )
            )
    elif (
        event.source_qualification_receipt_digest
        or event.wheel_build_count
        or event.qualification_increment
        or event.materialization_count
    ):
        diagnostics.append(
            _diagnostic("RELEASE_EVENT_COUNT_MISMATCH", "action declares unrelated build counters")
        )
    if event.harness_error_count and RELEASE_STATES.index(expected_to) >= RELEASE_STATES.index(
        "provider-qualified"
    ):
        diagnostics.append(
            _diagnostic("CHECK_HARNESS_ERROR_UNRESOLVED", "release action requires zero harness errors")
        )
    ordered = tuple(sorted(diagnostics, key=lambda item: item.code))
    return ReleaseCheckResultV1(
        "BLOCKED" if ordered else "PASS", ordered, event.event_digest
    )


def _advance_state(
    state: AggregateReleaseStateV1, event: ReleaseEventV1
) -> AggregateReleaseStateV1:
    counts = _counts_dict(state.action_counts)
    for counter in _ACTION_COUNTERS[event.action]:
        counts[counter] += 1
    transition_key = canonical_digest(
        {
            "before_state_digest": state.state_digest,
            "event_digest": event.event_digest,
            "target_state": event.target_state,
        }
    )
    records = (*state.event_records, ReleaseEventRecordV1(event.event_id, event.action, event.event_digest, transition_key))
    bootstrap_keys = set(state.consumed_bootstrap_keys)
    if event.bootstrap_consumption_key:
        bootstrap_keys.add(event.bootstrap_consumption_key)
    candidate = replace(
        state,
        current_state=event.target_state,
        predecessor_receipt_digest=transition_key,
        action_counts=tuple((key, counts[key]) for key in ACTION_COUNT_KEYS),
        event_records=records,
        consumed_bootstrap_keys=tuple(sorted(bootstrap_keys)),
        state_digest="",
    )
    return replace(candidate, state_digest=canonical_digest(candidate._payload()))


@dataclass(frozen=True)
class ReleaseAdvancePlanV1:
    decision: str
    before_state: AggregateReleaseStateV1
    after_state: AggregateReleaseStateV1 | None
    event: ReleaseEventV1
    snapshot: ReleaseSnapshotV1
    diagnostics: tuple[ReleaseDiagnosticV1, ...]
    plan_digest: str
    planned_mutation_count: int
    mutation_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "ReleaseAdvancePlanV1",
            "decision": self.decision,
            "before_state": self.before_state.as_dict(),
            "after_state": self.after_state.as_dict() if self.after_state else None,
            "event": self.event.as_dict(),
            "snapshot": self.snapshot.as_dict(),
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "plan_digest": self.plan_digest,
            "planned_mutation_count": self.planned_mutation_count,
            "mutation_count": self.mutation_count,
        }


def plan_release_advance(
    state: AggregateReleaseStateV1,
    event: ReleaseEventV1,
    snapshot: ReleaseSnapshotV1,
) -> ReleaseAdvancePlanV1:
    check = check_release_transition(state, event)
    diagnostics = list(check.diagnostics)
    if snapshot.journal_status != "clean":
        diagnostics.append(
            _diagnostic("RELEASE_JOURNAL_NOT_CLEAN", "PARTIAL or RECOVERED journal blocks advance")
        )
    if snapshot.state_digest != state.state_digest:
        diagnostics.append(_diagnostic("RELEASE_PREIMAGE_DRIFT", "state preimage digest drifted"))
    if (
        snapshot.source_fingerprint != state.source_fingerprint
        or snapshot.plan_digest != state.plan_digest
        or snapshot.cost_digest != state.cost_digest
        or snapshot.compatibility_digest != state.compatibility_digest
    ):
        diagnostics.append(
            _diagnostic("SOURCE_FREEZE_DRIFT", "fresh source/Plan/cost/compat snapshot drifted")
        )
    ordered = tuple(sorted({item.code: item for item in diagnostics}.values(), key=lambda item: item.code))
    decision = check.decision if not ordered else "BLOCKED"
    after_state = _advance_state(state, event) if decision == "PASS" else None
    payload = {
        "decision": decision,
        "before_state_digest": state.state_digest,
        "after_state_digest": after_state.state_digest if after_state else "",
        "event_digest": event.event_digest,
        "snapshot_digest": snapshot.snapshot_digest,
        "diagnostics": [item.as_dict() for item in ordered],
        "planned_mutation_count": 3 if decision == "PASS" else 0,
    }
    return ReleaseAdvancePlanV1(
        decision=decision,
        before_state=state,
        after_state=after_state,
        event=event,
        snapshot=snapshot,
        diagnostics=ordered,
        plan_digest=canonical_digest(payload),
        planned_mutation_count=payload["planned_mutation_count"],
    )


@dataclass(frozen=True)
class ReleaseTransitionAuthorizationV1:
    schema_version: int
    authorization_id: str
    authorization_ref: str
    action: str
    event_id: str
    plan_digest: str
    before_state_digest: str
    source_fingerprint: str
    issued_at: str
    expires_at: str
    reusable: bool
    authorization_digest: str

    @classmethod
    def from_mapping(cls, value: object) -> ReleaseTransitionAuthorizationV1:
        fields = {
            "schema_version",
            "authorization_id",
            "authorization_ref",
            "action",
            "event_id",
            "plan_digest",
            "before_state_digest",
            "source_fingerprint",
            "issued_at",
            "expires_at",
            "reusable",
            "authorization_digest",
        }
        item = _closed(value, fields, code="RELEASE_AUTHORIZATION_FIELDS_MISMATCH")
        payload = {key: item[key] for key in fields - {"authorization_digest"}}
        if item["schema_version"] != 1 or item["reusable"] is not False:
            raise ValueError("RELEASE_AUTHORIZATION_POLICY_INVALID")
        action = _text(item["action"], code="RELEASE_AUTHORIZATION_ACTION_INVALID")
        if action not in _ACTION_TRANSITIONS:
            raise ValueError("RELEASE_AUTHORIZATION_ACTION_INVALID")
        for field in ("plan_digest", "before_state_digest", "source_fingerprint", "authorization_digest"):
            _text(item[field], code="RELEASE_AUTHORIZATION_DIGEST_INVALID", pattern=_DIGEST_RE)
        issued = _parse_timestamp(item["issued_at"], code="RELEASE_AUTHORIZATION_TIME_INVALID")
        expires = _parse_timestamp(item["expires_at"], code="RELEASE_AUTHORIZATION_TIME_INVALID")
        if issued >= expires:
            raise ValueError("RELEASE_AUTHORIZATION_TIME_INVALID")
        if item["authorization_digest"] != canonical_digest(payload):
            raise ValueError("RELEASE_AUTHORIZATION_DIGEST_MISMATCH")
        return cls(
            schema_version=1,
            authorization_id=_text(
                item["authorization_id"], code="RELEASE_AUTHORIZATION_ID_INVALID", pattern=_ID_RE
            ),
            authorization_ref=_safe_ref(
                item["authorization_ref"], code="RELEASE_AUTHORIZATION_REF_INVALID"
            ),
            action=action,
            event_id=_text(item["event_id"], code="RELEASE_EVENT_ID_INVALID", pattern=_ID_RE),
            plan_digest=item["plan_digest"],
            before_state_digest=item["before_state_digest"],
            source_fingerprint=item["source_fingerprint"],
            issued_at=item["issued_at"],
            expires_at=item["expires_at"],
            reusable=False,
            authorization_digest=item["authorization_digest"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authorization_id": self.authorization_id,
            "authorization_ref": self.authorization_ref,
            "action": self.action,
            "event_id": self.event_id,
            "plan_digest": self.plan_digest,
            "before_state_digest": self.before_state_digest,
            "source_fingerprint": self.source_fingerprint,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "reusable": self.reusable,
            "authorization_digest": self.authorization_digest,
        }


@dataclass(frozen=True)
class AggregateReleaseTransitionReceiptV1:
    status: str
    decision: str
    event_id: str
    action: str
    plan_digest: str
    authorization_digest: str
    before_state_digest: str
    after_state_digest: str
    error_code: str
    mutation_count: int
    receipt_digest: str

    @classmethod
    def build(
        cls,
        *,
        status: str,
        decision: str,
        plan: ReleaseAdvancePlanV1,
        authorization_digest: str,
        error_code: str,
        mutation_count: int,
    ) -> AggregateReleaseTransitionReceiptV1:
        payload = {
            "schema_version": 1,
            "kind": "AggregateReleaseTransitionReceiptV1",
            "status": status,
            "decision": decision,
            "event_id": plan.event.event_id,
            "action": plan.event.action,
            "plan_digest": plan.plan_digest,
            "authorization_digest": authorization_digest,
            "before_state_digest": plan.before_state.state_digest,
            "after_state_digest": plan.after_state.state_digest if plan.after_state else "",
            "error_code": error_code,
            "mutation_count": mutation_count,
        }
        return cls(**{key: payload[key] for key in payload if key not in {"schema_version", "kind"}}, receipt_digest=canonical_digest(payload))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "AggregateReleaseTransitionReceiptV1",
            "status": self.status,
            "decision": self.decision,
            "event_id": self.event_id,
            "action": self.action,
            "plan_digest": self.plan_digest,
            "authorization_digest": self.authorization_digest,
            "before_state_digest": self.before_state_digest,
            "after_state_digest": self.after_state_digest,
            "error_code": self.error_code,
            "mutation_count": self.mutation_count,
            "receipt_digest": self.receipt_digest,
        }


class ReleaseWriteError(RuntimeError):
    def __init__(self, code: str, *, status: str, mutation_count: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.mutation_count = mutation_count


class ReleaseWriter(Protocol):
    def commit(
        self,
        receipt: Mapping[str, Any],
        state: Mapping[str, Any],
        *,
        ledger_preimage_digest: str,
        projection_preimage_digest: str,
    ) -> int: ...

    def inspect(self, event_id: str) -> tuple[Mapping[str, Any], ...]: ...

    def recover(self, event_id: str, state: Mapping[str, Any]) -> int: ...


def _empty_digest() -> str:
    return hashlib.sha256(b"").hexdigest()


class InMemoryReleaseWriter:
    """测试与 dry-run dogfood writer；失败后保留 PREPARED 事实。"""

    def __init__(self, *, fail_at: str = "") -> None:
        self.fail_at = fail_at
        self.journal: list[dict[str, Any]] = []
        self.projection: dict[str, Any] | None = None

    def _ledger_digest(self) -> str:
        raw = "".join(canonical_json(item) + "\n" for item in self.journal).encode()
        return hashlib.sha256(raw).hexdigest()

    def _projection_digest(self) -> str:
        if self.projection is None:
            return _empty_digest()
        return hashlib.sha256((canonical_json(self.projection) + "\n").encode()).hexdigest()

    def preimage_digests(self) -> tuple[str, str]:
        return self._ledger_digest(), self._projection_digest()

    def commit(
        self,
        receipt: Mapping[str, Any],
        state: Mapping[str, Any],
        *,
        ledger_preimage_digest: str,
        projection_preimage_digest: str,
    ) -> int:
        if self.preimage_digests() != (ledger_preimage_digest, projection_preimage_digest):
            raise ReleaseWriteError("RELEASE_WRITER_PREIMAGE_DRIFT", status="BLOCKED", mutation_count=0)
        if self.fail_at == "append":
            raise ReleaseWriteError("RELEASE_LEDGER_APPEND_FAILED", status="BLOCKED", mutation_count=0)
        prepared = {"journal_state": "PREPARED", "event_id": receipt["event_id"], "receipt": dict(receipt)}
        self.journal.append(prepared)
        if self.fail_at == "projection":
            raise ReleaseWriteError("RELEASE_PROJECTION_FAILED", status="PARTIAL", mutation_count=1)
        self.projection = dict(state)
        if self.fail_at == "commit":
            raise ReleaseWriteError("RELEASE_COMMIT_MARKER_FAILED", status="PARTIAL", mutation_count=2)
        self.journal.append({"journal_state": "COMMITTED", "event_id": receipt["event_id"], "receipt_digest": receipt["receipt_digest"]})
        return 3

    def inspect(self, event_id: str) -> tuple[Mapping[str, Any], ...]:
        return tuple(item for item in self.journal if item.get("event_id") == event_id)

    def recover(self, event_id: str, state: Mapping[str, Any]) -> int:
        records = self.inspect(event_id)
        if not records or records[0].get("journal_state") != "PREPARED" or any(
            item.get("journal_state") in {"COMMITTED", "RECOVERED"} for item in records
        ):
            raise ReleaseWriteError("RELEASE_RECOVERY_NOT_APPLICABLE", status="BLOCKED", mutation_count=0)
        self.projection = dict(state)
        self.journal.append({"journal_state": "RECOVERED", "event_id": event_id})
        return 2


class FileReleaseWriter:
    """只写调用方已解析的 release ledger/projection；PREPARED 后不回删历史。"""

    def __init__(self, ledger_path: Path, projection_path: Path, *, fail_at: str = "") -> None:
        self.ledger_path = ledger_path
        self.projection_path = projection_path
        self.fail_at = fail_at

    @staticmethod
    def _bytes(path: Path) -> bytes:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ReleaseWriteError(
                "RELEASE_WRITER_TARGET_INVALID", status="BLOCKED", mutation_count=0
            )
        return path.read_bytes() if path.is_file() else b""

    @classmethod
    def _digest(cls, path: Path) -> str:
        return hashlib.sha256(cls._bytes(path)).hexdigest()

    @staticmethod
    def _append(path: Path, value: Mapping[str, Any]) -> None:
        ensure_transaction_directory(path.parent)
        before = FileReleaseWriter._bytes(path)
        atomic_replace_bytes(
            path,
            before + (canonical_json(value) + "\n").encode("utf-8"),
        )

    @staticmethod
    def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
        ensure_transaction_directory(path.parent)
        atomic_replace_bytes(
            path,
            (canonical_json(value) + "\n").encode("utf-8"),
        )

    def commit(
        self,
        receipt: Mapping[str, Any],
        state: Mapping[str, Any],
        *,
        ledger_preimage_digest: str,
        projection_preimage_digest: str,
    ) -> int:
        if (self._digest(self.ledger_path), self._digest(self.projection_path)) != (
            ledger_preimage_digest,
            projection_preimage_digest,
        ):
            raise ReleaseWriteError(
                "RELEASE_WRITER_PREIMAGE_DRIFT", status="BLOCKED", mutation_count=0
            )
        if self.fail_at == "append":
            raise ReleaseWriteError(
                "RELEASE_LEDGER_APPEND_FAILED", status="BLOCKED", mutation_count=0
            )
        prepared = {
            "journal_state": "PREPARED",
            "event_id": receipt["event_id"],
            "receipt": dict(receipt),
        }
        self._append(self.ledger_path, prepared)
        if self.fail_at == "projection":
            raise ReleaseWriteError(
                "RELEASE_PROJECTION_FAILED", status="PARTIAL", mutation_count=1
            )
        self._write_atomic(self.projection_path, state)
        if self.fail_at == "commit":
            raise ReleaseWriteError(
                "RELEASE_COMMIT_MARKER_FAILED", status="PARTIAL", mutation_count=2
            )
        self._append(
            self.ledger_path,
            {
                "journal_state": "COMMITTED",
                "event_id": receipt["event_id"],
                "receipt_digest": receipt["receipt_digest"],
            },
        )
        return 3

    def inspect(self, event_id: str) -> tuple[Mapping[str, Any], ...]:
        raw = self._bytes(self.ledger_path)
        records: list[Mapping[str, Any]] = []
        for line in raw.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReleaseWriteError(
                    "RELEASE_LEDGER_INVALID", status="BLOCKED", mutation_count=0
                ) from exc
            if not isinstance(item, Mapping):
                raise ReleaseWriteError(
                    "RELEASE_LEDGER_INVALID", status="BLOCKED", mutation_count=0
                )
            if item.get("event_id") == event_id:
                records.append(item)
        return tuple(records)

    def recover(self, event_id: str, state: Mapping[str, Any]) -> int:
        records = self.inspect(event_id)
        if not records or records[0].get("journal_state") != "PREPARED" or any(
            item.get("journal_state") in {"COMMITTED", "RECOVERED"} for item in records
        ):
            raise ReleaseWriteError(
                "RELEASE_RECOVERY_NOT_APPLICABLE", status="BLOCKED", mutation_count=0
            )
        self._write_atomic(self.projection_path, state)
        self._append(
            self.ledger_path,
            {"journal_state": "RECOVERED", "event_id": event_id},
        )
        return 2


def _authorization_error(
    plan: ReleaseAdvancePlanV1,
    authorization: ReleaseTransitionAuthorizationV1,
    fresh: ReleaseSnapshotV1,
    *,
    now: datetime,
) -> str:
    if plan.decision != "PASS" or plan.after_state is None:
        return "RELEASE_PLAN_NOT_READY"
    if (
        authorization.plan_digest != plan.plan_digest
        or authorization.before_state_digest != plan.before_state.state_digest
        or authorization.source_fingerprint != plan.before_state.source_fingerprint
        or authorization.action != plan.event.action
        or authorization.event_id != plan.event.event_id
    ):
        return "RELEASE_AUTHORIZATION_SCOPE_MISMATCH"
    if not (
        _parse_timestamp(authorization.issued_at, code="RELEASE_AUTHORIZATION_TIME_INVALID")
        <= now.astimezone(UTC)
        < _parse_timestamp(authorization.expires_at, code="RELEASE_AUTHORIZATION_TIME_INVALID")
    ):
        return "RELEASE_AUTHORIZATION_EXPIRED"
    if fresh.snapshot_digest != plan.snapshot.snapshot_digest or fresh.journal_status != "clean":
        return "RELEASE_FRESH_PREIMAGE_MISMATCH"
    return ""


def apply_release_advance(
    plan: ReleaseAdvancePlanV1,
    authorization: ReleaseTransitionAuthorizationV1,
    fresh: ReleaseSnapshotV1,
    writer: ReleaseWriter,
    *,
    now: datetime | None = None,
) -> AggregateReleaseTransitionReceiptV1:
    current = now or datetime.now(UTC)
    error = _authorization_error(plan, authorization, fresh, now=current)
    if error:
        return AggregateReleaseTransitionReceiptV1.build(
            status="BLOCKED",
            decision="BLOCKED",
            plan=plan,
            authorization_digest=authorization.authorization_digest,
            error_code=error,
            mutation_count=0,
        )
    provisional = AggregateReleaseTransitionReceiptV1.build(
        status="PASS",
        decision="PASS",
        plan=plan,
        authorization_digest=authorization.authorization_digest,
        error_code="",
        mutation_count=3,
    )
    try:
        actual = writer.commit(
            provisional.as_dict(),
            plan.after_state.as_dict(),  # type: ignore[union-attr]
            ledger_preimage_digest=fresh.ledger_preimage_digest,
            projection_preimage_digest=fresh.projection_preimage_digest,
        )
    except ReleaseWriteError as exc:
        return AggregateReleaseTransitionReceiptV1.build(
            status=exc.status,
            decision="BLOCKED",
            plan=plan,
            authorization_digest=authorization.authorization_digest,
            error_code=exc.code,
            mutation_count=exc.mutation_count,
        )
    return replace(provisional, mutation_count=actual)


def inspect_release_journal(writer: ReleaseWriter, event_id: str) -> dict[str, Any]:
    records = writer.inspect(event_id)
    states = [str(item.get("journal_state") or "") for item in records]
    if "COMMITTED" in states:
        status = "PASS"
    elif "RECOVERED" in states:
        status = "RECOVERED"
    elif "PREPARED" in states:
        status = "PARTIAL"
    else:
        status = "ABSENT"
    payload = {
        "schema_version": 1,
        "kind": "ReleaseJournalInspectionV1",
        "event_id": event_id,
        "status": status,
        "record_count": len(records),
        "mutation_count": 0,
    }
    payload["inspection_digest"] = canonical_digest(payload)
    return payload


def recover_release_transition(
    plan: ReleaseAdvancePlanV1,
    authorization: ReleaseTransitionAuthorizationV1,
    fresh: ReleaseSnapshotV1,
    writer: ReleaseWriter,
    *,
    now: datetime | None = None,
) -> AggregateReleaseTransitionReceiptV1:
    current = now or datetime.now(UTC)
    if plan.decision != "PASS" or plan.after_state is None:
        error = "RELEASE_PLAN_NOT_READY"
    elif fresh.journal_status != "partial":
        error = "RELEASE_RECOVERY_NOT_APPLICABLE"
    elif (
        authorization.plan_digest != plan.plan_digest
        or authorization.before_state_digest != plan.before_state.state_digest
        or authorization.source_fingerprint != plan.before_state.source_fingerprint
        or authorization.action != plan.event.action
        or authorization.event_id != plan.event.event_id
    ):
        error = "RELEASE_AUTHORIZATION_SCOPE_MISMATCH"
    elif not (
        _parse_timestamp(
            authorization.issued_at, code="RELEASE_AUTHORIZATION_TIME_INVALID"
        )
        <= current.astimezone(UTC)
        < _parse_timestamp(
            authorization.expires_at, code="RELEASE_AUTHORIZATION_TIME_INVALID"
        )
    ):
        error = "RELEASE_AUTHORIZATION_EXPIRED"
    elif (
        fresh.state_digest != plan.before_state.state_digest
        or fresh.source_fingerprint != plan.before_state.source_fingerprint
        or fresh.plan_digest != plan.before_state.plan_digest
        or fresh.cost_digest != plan.before_state.cost_digest
        or fresh.compatibility_digest != plan.before_state.compatibility_digest
    ):
        error = "RELEASE_FRESH_PREIMAGE_MISMATCH"
    else:
        error = ""
    if error or plan.after_state is None:
        return AggregateReleaseTransitionReceiptV1.build(
            status="BLOCKED",
            decision="BLOCKED",
            plan=plan,
            authorization_digest=authorization.authorization_digest,
            error_code=error or "RELEASE_PLAN_NOT_READY",
            mutation_count=0,
        )
    try:
        mutation_count = writer.recover(plan.event.event_id, plan.after_state.as_dict())
    except ReleaseWriteError as exc:
        return AggregateReleaseTransitionReceiptV1.build(
            status=exc.status,
            decision="BLOCKED",
            plan=plan,
            authorization_digest=authorization.authorization_digest,
            error_code=exc.code,
            mutation_count=exc.mutation_count,
        )
    return AggregateReleaseTransitionReceiptV1.build(
        status="RECOVERED",
        decision="BLOCKED",
        plan=plan,
        authorization_digest=authorization.authorization_digest,
        error_code="RELEASE_RECOVERED_REVIEW_REQUIRED",
        mutation_count=mutation_count,
    )


__all__ = [
    "ACTION_COUNT_KEYS",
    "AggregateReleaseStateV1",
    "AggregateReleaseTransitionReceiptV1",
    "FileReleaseWriter",
    "InMemoryReleaseWriter",
    "RELEASE_STATES",
    "ReleaseAdvancePlanV1",
    "ReleaseEventV1",
    "ReleaseSnapshotV1",
    "ReleaseTransitionAuthorizationV1",
    "apply_release_advance",
    "build_initial_release_state",
    "check_release_transition",
    "inspect_release_journal",
    "plan_release_advance",
    "recover_release_transition",
]
