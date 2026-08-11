"""Machine-readable checkpoint result schema and summary rendering."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any

from meta_flow.checks import state_transition
from meta_flow.checks.token_budget import DEFAULT_READ_DENY_PATTERNS
from meta_flow.context_pack import read_expansion
from meta_flow.execution_control.contract import FINGERPRINT_KEYS, canonical_digest
from meta_flow.policies import failure_routing
from meta_flow.project.process_route import (
    ProcessRouteError,
    _resolve_runtime_path,
    _resolve_runtime_ref,
    format_runtime_ref,
)
from meta_flow.semantics import outcome
from meta_flow.state import checkpoint_projection, event_ledger
from meta_flow.state.current import now_utc

if TYPE_CHECKING:
    from meta_flow.execution_control.closure import ClosureCohortV1, ClosureInventoryItemV1

CHECKPOINT_LEDGER_REL = Path("process/state/CHECKPOINT-LEDGER.ndjson")
ITEM_STATUSES = {"PASS", "FAIL", "BLOCKED", "N/A", "WAIVED"}
GENERAL_DECISIONS = outcome.GENERAL_VERIFICATION_DECISIONS
CP7_DECISIONS = outcome.CP7_VERIFICATION_DECISIONS
EVIDENCE_STATUSES = {
    "MISSING_REQUIRED_EVIDENCE",
    "EXECUTED_NEGATIVE_RESULT",
    "EXECUTED_POSITIVE_RESULT",
    "DEFERRED_FOLLOW_UP",
    "NOT_APPLICABLE",
    "NEEDS_REVIEW",
}
RELEASE_DECISIONS = outcome.RELEASE_DECISIONS
FACT_DIFF_DECISION_IMPACTS = {"READY", "READY_WITH_RISK", "NOT_READY", "NO_IMPACT"}
SEVERITIES = {"BLOCKER", "HIGH", "MEDIUM", "LOW", "INFO"}
CHECKPOINT_RE = re.compile(r"^CP[0-8]$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _ref_path(value: Any) -> str:
    if isinstance(value, dict):
        raw = str(value.get("path") or value.get("ref") or "")
    else:
        raw = str(value or "")
    return raw.split("#", 1)[0]


def _matches_any(rel_path: str, patterns: tuple[str, ...]) -> bool:
    from fnmatch import fnmatch

    return any(rel_path == pattern or fnmatch(rel_path, pattern) for pattern in patterns)


def _deny_default_refs(result: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("context_ref", "evidence_ref"):
        path = _ref_path(result.get(key))
        if path and _matches_any(path, DEFAULT_READ_DENY_PATTERNS):
            refs.append(path)
    for item in _as_list(result.get("items")):
        if not isinstance(item, dict):
            continue
        for ref in _as_list(item.get("evidence_refs")):
            path = _ref_path(ref)
            if path and _matches_any(path, DEFAULT_READ_DENY_PATTERNS):
                refs.append(path)
    return sorted(set(refs))


def _validate_cp2_commitments(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    commitments = result.get("commitments")
    if commitments is None:
        return errors
    if not isinstance(commitments, dict):
        return ["commitments must be an object"]
    required_evidence = commitments.get("required_evidence", [])
    if required_evidence is None:
        return errors
    if not isinstance(required_evidence, list):
        return ["commitments.required_evidence must be a list"]
    seen: set[str] = set()
    for index, entry in enumerate(required_evidence, 1):
        if not isinstance(entry, dict):
            errors.append(f"commitments.required_evidence[{index}] must be an object")
            continue
        for key in ("id", "kind", "required_stage"):
            if not entry.get(key):
                errors.append(f"commitments.required_evidence[{index}] missing {key}")
        evidence_id = str(entry.get("id") or "")
        if evidence_id in seen:
            errors.append(f"commitments.required_evidence[{index}] duplicate id: {evidence_id}")
        seen.add(evidence_id)
        if entry.get("required_stage") and str(entry["required_stage"]) != "CP7":
            errors.append(f"commitments.required_evidence[{index}] required_stage must be CP7")
        minimum = entry.get("minimum_evidence")
        if minimum is not None and not isinstance(minimum, dict):
            errors.append(
                f"commitments.required_evidence[{index}] minimum_evidence must be an object"
            )
    return errors


def _validate_cp7_alignment(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    alignment = result.get("promise_evidence_alignment")
    if alignment is None:
        return errors
    if not isinstance(alignment, list):
        return ["promise_evidence_alignment must be a list"]
    missing_required_seen = False
    for index, item in enumerate(alignment, 1):
        if not isinstance(item, dict):
            errors.append(f"promise_evidence_alignment[{index}] must be an object")
            continue
        for key in ("promise_ref", "evidence_status", "result"):
            if not item.get(key):
                errors.append(f"promise_evidence_alignment[{index}] missing {key}")
        status = str(item.get("evidence_status") or "")
        if status and status not in EVIDENCE_STATUSES:
            errors.append(f"promise_evidence_alignment[{index}] invalid evidence_status: {status}")
        result_value = str(item.get("result") or "")
        if result_value and result_value not in {
            "PASS",
            "FAIL",
            "BLOCKED",
            "NEEDS_REVIEW",
            "PASS_WITH_RISK",
        }:
            errors.append(f"promise_evidence_alignment[{index}] invalid result: {result_value}")
        evidence_refs = item.get("evidence_refs") or []
        if evidence_refs and not isinstance(evidence_refs, list):
            errors.append(f"promise_evidence_alignment[{index}] evidence_refs must be a list")
        if status == "MISSING_REQUIRED_EVIDENCE":
            missing_required_seen = True
            if result_value != "BLOCKED":
                errors.append(
                    f"promise_evidence_alignment[{index}] missing required evidence must result BLOCKED"
                )
        if status == "EXECUTED_NEGATIVE_RESULT" and not evidence_refs:
            errors.append(
                f"promise_evidence_alignment[{index}] executed negative result requires evidence_refs"
            )
    if missing_required_seen and str(result.get("decision") or "") != "BLOCKED":
        errors.append("CP7 decision must be BLOCKED when required evidence is missing")
    return errors


def _validate_cp8_fact_diff(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    release_decision = str(result.get("release_decision") or "")
    if release_decision and release_decision not in RELEASE_DECISIONS:
        errors.append(f"invalid release_decision for CP8: {release_decision}")
    fact_diff = result.get("fact_diff")
    if fact_diff is None:
        return errors
    if not isinstance(fact_diff, list):
        return ["fact_diff must be a list"]
    missing_required_seen = False
    risk_seen = False
    not_ready_impact_seen = False
    ready_with_risk_impact_seen = False
    for index, item in enumerate(fact_diff, 1):
        if not isinstance(item, dict):
            errors.append(f"fact_diff[{index}] must be an object")
            continue
        for key in ("promise_ref", "promise", "status", "decision_impact"):
            if not item.get(key):
                errors.append(f"fact_diff[{index}] missing {key}")
        status = str(item.get("status") or "")
        if status and status not in EVIDENCE_STATUSES:
            errors.append(f"fact_diff[{index}] invalid status: {status}")
        decision_impact = str(item.get("decision_impact") or "")
        if decision_impact and decision_impact not in FACT_DIFF_DECISION_IMPACTS:
            errors.append(f"fact_diff[{index}] invalid decision_impact: {decision_impact}")
        evidence_refs = item.get("evidence_refs") or []
        if evidence_refs and not isinstance(evidence_refs, list):
            errors.append(f"fact_diff[{index}] evidence_refs must be a list")
        if status == "MISSING_REQUIRED_EVIDENCE":
            missing_required_seen = True
            if decision_impact != "NOT_READY":
                errors.append(
                    f"fact_diff[{index}] missing required evidence must have decision_impact NOT_READY"
                )
        if status in {"EXECUTED_NEGATIVE_RESULT", "DEFERRED_FOLLOW_UP", "NEEDS_REVIEW"}:
            risk_seen = True
            if status == "EXECUTED_NEGATIVE_RESULT" and not evidence_refs:
                errors.append(f"fact_diff[{index}] executed negative result requires evidence_refs")
        if decision_impact == "NOT_READY":
            not_ready_impact_seen = True
        if decision_impact == "READY_WITH_RISK":
            ready_with_risk_impact_seen = True
    decision = str(result.get("decision") or "")
    if missing_required_seen:
        if decision in {"PASS", "WAIVED"}:
            errors.append(
                "CP8 decision cannot be PASS/WAIVED when fact_diff has missing required evidence"
            )
        if release_decision and release_decision != "NOT_READY":
            errors.append(
                "CP8 release_decision must be NOT_READY when fact_diff has missing required evidence"
            )
    if release_decision == "READY":
        if risk_seen or ready_with_risk_impact_seen or not_ready_impact_seen:
            errors.append(
                "CP8 release_decision cannot be READY when fact_diff has risk or not-ready impacts"
            )
    if release_decision == "READY_WITH_RISK" and not_ready_impact_seen:
        errors.append(
            "CP8 release_decision cannot be READY_WITH_RISK when fact_diff has NOT_READY impacts"
        )
    return errors


def _validate_checker_provenance(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    provenance = result.get("checker_provenance")
    if provenance is None:
        return errors
    if not isinstance(provenance, dict):
        return ["checker_provenance must be an object"]
    for key in ("checker_name", "invocation", "generated_by", "fallback_used"):
        if key not in provenance:
            errors.append(f"checker_provenance missing {key}")
    if not (provenance.get("checker_version") or provenance.get("checker_commit")):
        errors.append("checker_provenance requires checker_version or checker_commit")
    if "fallback_used" in provenance and not isinstance(provenance.get("fallback_used"), bool):
        errors.append("checker_provenance.fallback_used must be a boolean")
    if provenance.get("fallback_used") is True:
        for key in ("fallback_reason", "fallback_review_ref"):
            if not provenance.get(key):
                errors.append(f"checker_provenance fallback_used=true requires {key}")
    fallback_keys = ("fallback_reason", "fallback_review_ref")
    if provenance.get("fallback_used") is False and any(
        provenance.get(key) for key in fallback_keys
    ):
        errors.append("checker_provenance fallback fields require fallback_used=true")
    return errors


def _load_dispatch_events(root: Path) -> list[dict[str, Any]]:
    ledger_path = event_ledger.ledger_path(root, "dispatch")
    if not ledger_path.is_file():
        return []
    events, _errors = event_ledger.load_events(ledger_path)
    return events


def _input_artifact_path(root: Path, ref: str) -> Path:
    logical = Path(ref)
    if logical.is_absolute() or PureWindowsPath(ref).is_absolute() or ".." in logical.parts:
        raise ValueError(f"INPUT_HASH_PATH_INVALID: {ref}")
    candidate = _resolve_runtime_path(root, logical)
    allowed_root = (
        _resolve_runtime_ref(root, "process/PROJECT.yaml").parent
        if logical.parts and logical.parts[0] == "process"
        else root.resolve()
    )
    try:
        candidate.relative_to(allowed_root.resolve())
    except ValueError as exc:
        raise ValueError(f"INPUT_HASH_PATH_ESCAPE: {ref}") from exc
    return candidate


def build_input_artifact_hashes(
    project_root: Path,
    refs: list[str],
) -> dict[str, str]:
    """由原生模块生成 CP strict correlation 的 file-byte digests。"""

    root = project_root.resolve()
    if not refs or len(set(refs)) != len(refs):
        raise ValueError("input artifact refs must be non-empty and unique")
    hashes: dict[str, str] = {}
    for ref in sorted(refs):
        candidate = _input_artifact_path(root, ref)
        if not candidate.is_file():
            raise ValueError(f"INPUT_HASH_MISSING: {ref}")
        hashes[ref] = "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest()
    return hashes


@dataclass(frozen=True, slots=True)
class CpEvidenceInventoryProjectionV1:
    """Checkpoint owner 投影出的只读 result/evidence inventory。"""

    result_items: tuple[ClosureInventoryItemV1, ...]
    evidence_items: tuple[ClosureInventoryItemV1, ...]
    findings: tuple[str, ...]
    mutation_count: int = 0


@dataclass(frozen=True, slots=True)
class NativeClosureAuthorityProjectionV1:
    """由 canonical CP6 current head 与 exact Return/Evidence 派生的只读 authority。"""

    decision: str
    reason_codes: tuple[str, ...]
    story_id: str
    cr_id: str
    cohort_revision: int
    result_ref: str
    result_digest: str
    checkpoint_event_id: str
    checkpoint_ledger_digest: str
    return_ref: str
    return_digest: str
    evidence_ref: str
    evidence_digest: str
    input_artifact_hashes: tuple[tuple[str, str], ...]
    container_refs: tuple[str, ...]
    dispatch_refs: tuple[str, ...]
    receipt_refs: tuple[str, ...]
    bounded_refs: tuple[str, ...]
    fingerprints: tuple[tuple[str, str], ...]
    authority_digest: str
    mutation_count: int = 0

    def as_dict(self, *, include_authority_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
            "story_id": self.story_id,
            "cr_id": self.cr_id,
            "cohort_revision": self.cohort_revision,
            "result_ref": self.result_ref,
            "result_digest": self.result_digest,
            "checkpoint_event_id": self.checkpoint_event_id,
            "checkpoint_ledger_digest": self.checkpoint_ledger_digest,
            "return_ref": self.return_ref,
            "return_digest": self.return_digest,
            "evidence_ref": self.evidence_ref,
            "evidence_digest": self.evidence_digest,
            "input_artifact_hashes": dict(self.input_artifact_hashes),
            "container_refs": list(self.container_refs),
            "dispatch_refs": list(self.dispatch_refs),
            "receipt_refs": list(self.receipt_refs),
            "bounded_refs": list(self.bounded_refs),
            "fingerprints": dict(self.fingerprints),
            "mutation_count": self.mutation_count,
        }
        if include_authority_digest:
            payload["authority_digest"] = self.authority_digest
        return payload


def _blocked_closure_authority(
    *,
    story_id: str,
    expected_cohort_revision: int,
    reasons: list[str],
    cr_id: str = "",
) -> NativeClosureAuthorityProjectionV1:
    revision = (
        expected_cohort_revision
        if type(expected_cohort_revision) is int and expected_cohort_revision > 0
        else 1
    )
    empty_fingerprints = tuple(
        (key, hashlib.sha256(b"").hexdigest()) for key in sorted(FINGERPRINT_KEYS)
    )
    partial = NativeClosureAuthorityProjectionV1(
        decision="BLOCKED",
        reason_codes=tuple(sorted(set(reasons))),
        story_id=story_id,
        cr_id=cr_id,
        cohort_revision=revision,
        result_ref="",
        result_digest="",
        checkpoint_event_id="",
        checkpoint_ledger_digest="",
        return_ref="",
        return_digest="",
        evidence_ref="",
        evidence_digest="",
        input_artifact_hashes=(),
        container_refs=(),
        dispatch_refs=(),
        receipt_refs=(),
        bounded_refs=(),
        fingerprints=empty_fingerprints,
        authority_digest="",
    )
    return partial


def _json_mapping(path: Path, *, subject: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{subject} must be one readable UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{subject} must be one JSON object")
    return value


def project_native_closure_authority(
    project_root: Path,
    *,
    story_id: str,
    expected_cohort_revision: int,
) -> NativeClosureAuthorityProjectionV1:
    """定位 unit-bound CP6 current head；caller 不能提交 authority/ref/digest。"""

    root = project_root.resolve()
    if not story_id or type(expected_cohort_revision) is not int or expected_cohort_revision < 1:
        return _blocked_closure_authority(
            story_id=story_id,
            expected_cohort_revision=max(expected_cohort_revision, 1),
            reasons=["CLOSURE_AUTHORITY_INPUT_INVALID"],
        )
    ledger_path = _resolve_runtime_ref(root, CHECKPOINT_LEDGER_REL.as_posix())
    events, ledger_errors = event_ledger.load_events(ledger_path)
    candidates = [
        item
        for item in events
        if str(item.get("checkpoint") or "").upper() == "CP6"
        and str(item.get("story_id") or "") == story_id
    ]
    cr_ids = {str(item.get("cr_id") or "") for item in candidates if item.get("cr_id")}
    if ledger_errors or len(cr_ids) != 1:
        return _blocked_closure_authority(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            reasons=[*ledger_errors, "CLOSURE_CP6_LEDGER_IDENTITY_UNAVAILABLE"],
        )
    cr_id = next(iter(cr_ids))
    projection = checkpoint_projection.load_checkpoint_projection(
        root,
        cr_id=cr_id,
        checkpoint="CP6",
    )
    head = projection.head("CP6", subject_id=story_id)
    if projection.decision != "PASS" or head is None:
        return _blocked_closure_authority(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            cr_id=cr_id,
            reasons=[
                *(item.code for item in projection.findings),
                "CLOSURE_CP6_CURRENT_HEAD_UNAVAILABLE",
            ],
        )
    matching_events = [item for item in candidates if item.get("event_id") == head.event_id]
    if len(matching_events) != 1:
        return _blocked_closure_authority(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            cr_id=cr_id,
            reasons=["CLOSURE_CP6_LEDGER_EVENT_AMBIGUOUS"],
        )
    result_ref = head.result_ref
    try:
        result_path = _input_artifact_path(root, result_ref)
        result_bytes = result_path.read_bytes()
        result = _json_mapping(result_path, subject="CP6 result")
    except (OSError, TypeError, ValueError) as exc:
        return _blocked_closure_authority(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            cr_id=cr_id,
            reasons=[f"CLOSURE_CP6_RESULT_INVALID_{type(exc).__name__.upper()}"],
        )
    errors, warnings = validate_cp_result(
        result_path,
        project_root=root,
        check_consistency=True,
        correlation_profile="strict",
    )
    result_revision = result.get("closure_cohort_revision", result.get("check_attempt"))
    if (
        errors
        or warnings
        or result.get("decision") != "PASS"
        or result.get("story_id") != story_id
        or result.get("cr_id") != cr_id
        or result_revision != expected_cohort_revision
    ):
        return _blocked_closure_authority(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            cr_id=cr_id,
            reasons=[
                *(f"CP6_ERROR:{item}" for item in errors),
                *(f"CP6_WARNING:{item}" for item in warnings),
                "CLOSURE_CP6_STRICT_CORRELATION_FAILED",
            ],
        )
    declared_hashes = result.get("input_artifact_hashes")
    if not isinstance(declared_hashes, Mapping) or not declared_hashes:
        return _blocked_closure_authority(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            cr_id=cr_id,
            reasons=["CLOSURE_CP6_INPUT_HASHES_REQUIRED"],
        )
    normalized_hashes: list[tuple[str, str]] = []
    hash_findings: list[str] = []
    for raw_ref, raw_digest in sorted(declared_hashes.items()):
        ref = str(raw_ref)
        digest = str(raw_digest)
        if not SHA256_RE.fullmatch(digest):
            hash_findings.append(f"CLOSURE_INPUT_HASH_INVALID:{ref}")
            continue
        try:
            actual = "sha256:" + hashlib.sha256(_input_artifact_path(root, ref).read_bytes()).hexdigest()
        except (OSError, ValueError):
            actual = ""
        if actual != digest:
            hash_findings.append(f"CLOSURE_INPUT_HASH_DRIFT:{ref}")
        normalized_hashes.append((ref, digest))
    evidence_ref = str(result.get("evidence_ref") or "")
    return_refs = [ref for ref, _ in normalized_hashes if ref.startswith("process/returns/")]
    if len(return_refs) != 1 or evidence_ref not in dict(normalized_hashes):
        hash_findings.append("CLOSURE_RETURN_EVIDENCE_BINDING_INCOMPLETE")
    if hash_findings:
        return _blocked_closure_authority(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            cr_id=cr_id,
            reasons=hash_findings,
        )
    return_ref = return_refs[0]
    try:
        return_path = _input_artifact_path(root, return_ref)
        evidence_path = _input_artifact_path(root, evidence_ref)
        return_payload = _json_mapping(return_path, subject="Return Packet")
        evidence_payload = _json_mapping(evidence_path, subject="Evidence Index")
    except (OSError, ValueError) as exc:
        return _blocked_closure_authority(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            cr_id=cr_id,
            reasons=[f"CLOSURE_RETURN_EVIDENCE_INVALID_{type(exc).__name__.upper()}"],
        )
    if any(
        payload.get("story_id") != story_id or payload.get("cr_id") != cr_id
        for payload in (return_payload, evidence_payload)
    ):
        return _blocked_closure_authority(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            cr_id=cr_id,
            reasons=["CLOSURE_RETURN_EVIDENCE_IDENTITY_MISMATCH"],
        )
    container_ref = f"process/works/{cr_id}/WORK.yaml"
    container_refs = (container_ref,) if _input_artifact_path(root, container_ref).is_file() else ()
    dispatch_refs = tuple(sorted(str(item) for item in _as_list(result.get("dispatch_refs")) if item))
    receipt_refs = tuple(
        sorted(
            ref
            for ref, _ in normalized_hashes
            if ref.endswith(".receipt.json") and "/evidence/validation/" in ref
        )
    )
    if not container_refs or not dispatch_refs or not receipt_refs:
        return _blocked_closure_authority(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            cr_id=cr_id,
            reasons=["CLOSURE_CANONICAL_OWNER_REF_SET_INCOMPLETE"],
        )
    result_digest = hashlib.sha256(result_bytes).hexdigest()
    return_digest = hashlib.sha256(return_path.read_bytes()).hexdigest()
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    checkpoint_ledger_digest = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    package_sources = {
        ref: hashlib.sha256((root / ref).read_bytes()).hexdigest()
        for ref in (
            "meta_flow/execution_control/contract.py",
            "meta_flow/execution_control/closure.py",
            "meta_flow/checks/cp_result.py",
        )
        if (root / ref).is_file()
    }
    fingerprint_payloads = {
        "facts": {"result": result_digest, "return": return_digest, "evidence": evidence_digest},
        "scope": {"container_refs": container_refs, "input_hashes": normalized_hashes},
        "authorization": {"checkpoint_event_id": head.event_id, "ledger": checkpoint_ledger_digest},
        "contract": package_sources,
        "consumer": {"story_id": story_id, "dispatch_refs": dispatch_refs},
        "ownership": {"touched_files": return_payload.get("touched_files", [])},
        "slice": {"cr_id": cr_id, "cohort_revision": expected_cohort_revision},
        "test": {"commands": evidence_payload.get("commands", []), "tests": evidence_payload.get("tests", [])},
        "source": {"checker": result.get("checker_provenance", {}), "package": package_sources},
        "profile": {"checkpoint": "CP6", "correlation": "strict"},
    }
    fingerprints = tuple(
        (key, canonical_digest(fingerprint_payloads[key])) for key in sorted(FINGERPRINT_KEYS)
    )
    bounded_refs = tuple(
        sorted(
            {
                result_ref,
                return_ref,
                evidence_ref,
                container_ref,
                *dispatch_refs,
                *receipt_refs,
                *(ref for ref, _ in normalized_hashes),
            }
        )
    )
    partial = NativeClosureAuthorityProjectionV1(
        decision="PASS",
        reason_codes=(),
        story_id=story_id,
        cr_id=cr_id,
        cohort_revision=expected_cohort_revision,
        result_ref=result_ref,
        result_digest=result_digest,
        checkpoint_event_id=head.event_id,
        checkpoint_ledger_digest=checkpoint_ledger_digest,
        return_ref=return_ref,
        return_digest=return_digest,
        evidence_ref=evidence_ref,
        evidence_digest=evidence_digest,
        input_artifact_hashes=tuple(normalized_hashes),
        container_refs=container_refs,
        dispatch_refs=dispatch_refs,
        receipt_refs=receipt_refs,
        bounded_refs=bounded_refs,
        fingerprints=fingerprints,
        authority_digest="",
    )
    return replace(
        partial,
        authority_digest=canonical_digest(partial.as_dict(include_authority_digest=False)),
    )


def _closure_evidence_refs(result: Mapping[str, Any]) -> tuple[str, ...]:
    refs = {_ref_path(result.get("evidence_ref"))}
    for item in _as_list(result.get("items")):
        if not isinstance(item, Mapping):
            continue
        refs.update(_ref_path(ref) for ref in _as_list(item.get("evidence_refs")))
    refs.discard("")
    return tuple(sorted(refs))


def project_cp_evidence_inventory(
    project_root: Path,
    *,
    cohort: ClosureCohortV1,
    result_refs: tuple[str, ...],
) -> CpEvidenceInventoryProjectionV1:
    """复用 result checker/current-head 语义，并只读核验 exact evidence bytes。"""

    # 保持 cp_result 为 closure 的 canonical owner，同时避免顶层循环导入。
    # 延迟导入让 closure 能在 closed registry 建立时冻结本函数对象本身。
    from meta_flow.execution_control.closure import inventory_item

    root = project_root.resolve()
    normalized_refs = tuple(sorted(str(ref) for ref in result_refs))
    if not normalized_refs or len(set(normalized_refs)) != len(normalized_refs):
        raise ValueError("result_refs must be non-empty and unique")
    result_items: list[ClosureInventoryItemV1] = []
    evidence_items: list[ClosureInventoryItemV1] = []
    findings: list[str] = []
    for result_ref in normalized_refs:
        result_path = _input_artifact_path(root, result_ref)
        errors, warnings = validate_cp_result(
            result_path,
            project_root=root,
            check_consistency=True,
            correlation_profile="strict",
        )
        findings.extend(f"{result_ref}:{finding}" for finding in (*errors, *warnings))
        result: dict[str, Any] = {}
        if result_path.is_file():
            try:
                result = load_cp_result(result_path)
            except ValueError as exc:
                findings.append(f"{result_ref}:{exc}")
        result_items.append(
            inventory_item(
                kind="result",
                ref=result_ref,
                cohort=cohort,
                dangling=bool(errors) or str(result.get("decision") or "") != "PASS",
            )
        )
        evidence_refs = _closure_evidence_refs(result)
        if not evidence_refs:
            evidence_refs = (f"{result_ref}#required-evidence-unavailable",)
        declared_hashes = result.get("input_artifact_hashes")
        if not isinstance(declared_hashes, Mapping):
            declared_hashes = {}
        for evidence_ref in evidence_refs:
            evidence_path = _input_artifact_path(root, evidence_ref)
            declared = str(declared_hashes.get(evidence_ref) or "")
            dangling = True
            if evidence_path.is_file() and SHA256_RE.fullmatch(declared):
                actual = "sha256:" + hashlib.sha256(evidence_path.read_bytes()).hexdigest()
                dangling = actual != declared
            if dangling:
                findings.append(f"{result_ref}:EVIDENCE_MISSING_OR_DIGEST_DRIFT:{evidence_ref}")
            evidence_items.append(
                inventory_item(
                    kind="evidence",
                    ref=evidence_ref,
                    cohort=cohort,
                    dangling=dangling,
                )
            )
    return CpEvidenceInventoryProjectionV1(
        result_items=tuple(result_items),
        evidence_items=tuple(evidence_items),
        findings=tuple(sorted(set(findings))),
    )


def _validate_dispatch_refs(root: Path, result: dict[str, Any]) -> list[str]:
    refs = [str(ref) for ref in _as_list(result.get("dispatch_refs")) if str(ref)]
    if not refs:
        return []
    checkpoint = str(result.get("checkpoint") or "")
    expected_roles = {"CP6": "meta-dev", "CP7": "meta-qa"}
    expected_role = expected_roles.get(checkpoint)
    if expected_role is None or str(result.get("decision") or "") == "N/A":
        return []
    events = _load_dispatch_events(root)
    if not events:
        return ["dispatch_refs require AGENT-DISPATCH-LEDGER entries: " + ", ".join(refs)]
    events_by_dispatch: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        dispatch_id = str(event.get("dispatch_id") or "")
        if dispatch_id:
            events_by_dispatch.setdefault(dispatch_id, []).append(event)
    errors: list[str] = []
    for ref in refs:
        matching = events_by_dispatch.get(ref, [])
        if not matching:
            errors.append(f"dispatch_refs missing from AGENT-DISPATCH-LEDGER: {ref}")
            continue
        projector = event_ledger.project_dispatch_attempt(
            event_ledger.ProjectionInputV1(tuple(matching), "dispatch", ref)
        )
        semantic_errors: list[str] = list(projector.finding_codes)
        for event in matching:
            event_type = str(event.get("event_type") or "")
            if event_type == "dispatch_not_required":
                semantic_errors.append("dispatch_not_required is invalid for applicable CP6/CP7")
            elif (
                event_type == "inline_fallback" and not str(event.get("approved_by") or "").strip()
            ):
                semantic_errors.append("inline fallback requires approved_by")
            elif event_type == "dispatch":
                if str(event.get("dispatch_mode") or "") == "inline-fallback":
                    semantic_errors.append("real dispatch has incompatible dispatch_mode")
                related_dispatch = [
                    candidate
                    for candidate in matching
                    if str(candidate.get("event_type") or "") == "dispatch"
                ]
                if not any(
                    str(candidate.get(field) or "").strip()
                    for candidate in related_dispatch
                    for field in ("agent_id", "thread_id")
                ):
                    semantic_errors.append("real dispatch requires agent_id or thread_id")
                if not any(
                    str(candidate.get(field) or "").strip()
                    for candidate in related_dispatch
                    for field in ("spawned_at", "resumed_at")
                ):
                    semantic_errors.append("real dispatch requires spawned_at or resumed_at")
                if not any(
                    str(candidate.get("dispatch_trigger") or "").strip()
                    for candidate in related_dispatch
                ):
                    semantic_errors.append("real dispatch requires dispatch_trigger")
            if str(event.get("canonical_role") or "") != expected_role:
                semantic_errors.append(f"canonical_role must be {expected_role}")
            if str(event.get("checkpoint") or "") != checkpoint:
                semantic_errors.append(f"checkpoint must be {checkpoint}")
        if not projector.terminal_success:
            semantic_errors.append("status must be terminal and successful")
        if semantic_errors:
            errors.append(
                f"dispatch_ref {ref} is not valid for {checkpoint}: "
                + "; ".join(dict.fromkeys(semantic_errors))
            )
    return errors


def _correlation_findings(root: Path, result_path: Path, result: dict[str, Any]) -> list[str]:
    """Validate new attempt/hash evidence without fabricating legacy facts."""

    findings = _canonical_checkpoint_findings(root, result_path, result)
    if (
        str(result.get("checkpoint") or "") not in {"CP6", "CP7"}
        or str(result.get("decision") or "") == "N/A"
    ):
        return findings
    attempt = result.get("check_attempt")
    if not isinstance(attempt, int) or attempt < 1:
        findings.append("LEGACY_ATTEMPT_UNAVAILABLE: check_attempt must be a positive integer")
    elif attempt > 1:
        ref = str(result.get("supersedes_result_ref") or "")
        previous = _resolve_runtime_path(root, ref) if ref else None
        if not ref or previous is None or not previous.is_file():
            findings.append(
                "RESULT_SUPERSEDES_MISSING: check_attempt>1 requires existing supersedes_result_ref"
            )
        else:
            try:
                prior = _read_json(previous)
            except ValueError:
                findings.append(
                    "RESULT_SUPERSEDES_INVALID: supersedes_result_ref is not a result object"
                )
            else:
                if (
                    prior.get("cr_id") != result.get("cr_id")
                    or prior.get("checkpoint") != result.get("checkpoint")
                    or prior.get("story_id") != result.get("story_id")
                ):
                    findings.append(
                        "RESULT_SUPERSEDES_IDENTITY_MISMATCH: prior result must share CR/checkpoint/story"
                    )
                if (
                    not isinstance(prior.get("check_attempt"), int)
                    or int(prior["check_attempt"]) >= attempt
                ):
                    findings.append(
                        "RESULT_SUPERSEDES_ORDER_INVALID: prior check_attempt must be smaller"
                    )
    hashes = result.get("input_artifact_hashes")
    if not isinstance(hashes, dict) or not hashes:
        findings.append("LEGACY_INPUT_HASH_UNAVAILABLE: input_artifact_hashes must be non-empty")
    else:
        for ref, declared in sorted(hashes.items()):
            try:
                candidate = _input_artifact_path(root, str(ref))
            except ValueError as exc:
                findings.append(str(exc))
                continue
            if not candidate.is_file():
                findings.append(f"INPUT_HASH_MISSING: {ref}")
                continue
            if not SHA256_RE.fullmatch(str(declared)):
                findings.append(f"INPUT_HASH_FORMAT_INVALID: {ref}")
                continue
            actual = "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest()
            if actual != declared:
                findings.append(f"INPUT_HASH_MISMATCH: {ref}")
    refs = [str(ref) for ref in _as_list(result.get("dispatch_refs")) if str(ref)]
    if refs:
        events = _load_dispatch_events(root)
        by_dispatch: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            if event.get("dispatch_id"):
                by_dispatch.setdefault(str(event["dispatch_id"]), []).append(event)
        for dispatch_id in refs:
            projected = event_ledger.project_dispatch_attempt(
                event_ledger.ProjectionInputV1(
                    tuple(by_dispatch.get(dispatch_id, [])),
                    "dispatch",
                    dispatch_id,
                )
            )
            if (
                "DISPATCH_NOT_FOUND" in projected.finding_codes
                or "TYPED_ATTEMPT_UNAVAILABLE" in projected.finding_codes
            ):
                findings.append(f"FINAL_ATTEMPT_UNAVAILABLE: {dispatch_id}")
                continue
            if not projected.terminal_success:
                findings.append(f"FINAL_ATTEMPT_NOT_UNIQUE_SUCCESS: {dispatch_id}")
    return findings


def _canonical_checkpoint_findings(
    root: Path,
    result_path: Path,
    result: Mapping[str, Any],
) -> list[str]:
    """只通过 canonical projection 校验 result 的 current-head 身份。"""

    cr_id = str(result.get("cr_id") or "")
    checkpoint = str(result.get("checkpoint") or result.get("checkpoint_id") or "").upper()
    if not cr_id or not CHECKPOINT_RE.fullmatch(checkpoint):
        return []
    projection = checkpoint_projection.load_checkpoint_projection(
        root,
        cr_id=cr_id,
        checkpoint=checkpoint,
    )
    findings = [
        f"CHECKPOINT_PROJECTION_{finding.code}: {finding.message}"
        for finding in projection.findings
    ]
    result_ref = format_runtime_ref(root, result_path)
    # Producer 可先校验尚未 append 的新 result；只有 ledger 已引用该 ref 时，
    # result-check 才对它施加 current-head 身份约束。append 前的图一致性由
    # preflight_checkpoint_ledger_append 在零写阶段负责。
    if result_ref not in projection.loaded_result_refs:
        return findings
    subject_id = str(result.get("story_id") or "") or cr_id
    head = projection.head(checkpoint, subject_id=subject_id)
    if head is None:
        findings.append(f"CHECKPOINT_CURRENT_HEAD_UNAVAILABLE: {cr_id}/{checkpoint}/{subject_id}")
    elif head.result_ref != result_ref:
        findings.append(
            f"CHECKPOINT_RESULT_NOT_CURRENT_HEAD: expected={head.result_ref}, actual={result_ref}"
        )
    elif head.decision != str(result.get("decision") or "").upper():
        findings.append("CHECKPOINT_RESULT_DECISION_MISMATCH")
    return findings


def _validate_derived_consistency(
    root: Path, result_path: Path, result: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    summary_ref = str(result.get("summary_ref") or "")
    summary_path = (
        _resolve_runtime_path(root, summary_ref)
        if summary_ref
        else result_path.with_suffix(".summary.md")
    )
    decision = str(result.get("decision") or "")
    checkpoint = str(result.get("checkpoint") or result.get("checkpoint_id") or "")
    cr_id = str(result.get("cr_id") or "")
    if summary_path.is_file():
        summary_text = summary_path.read_text(encoding="utf-8")
        if f"Decision: {decision}" not in summary_text:
            errors.append(f"summary decision does not match result JSON: {summary_path}")
        if checkpoint and f"# {checkpoint} Summary" not in summary_text:
            errors.append(f"summary checkpoint does not match result JSON: {summary_path}")
        if cr_id and f"CR: {cr_id}" not in summary_text:
            errors.append(f"summary CR does not match result JSON: {summary_path}")
    errors.extend(_validate_dispatch_refs(root, result))
    cr_index_path = _resolve_runtime_ref(root, "process/changes/CR-INDEX.json")
    if cr_id and cr_index_path.is_file():
        try:
            index = json.loads(cr_index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{cr_index_path} invalid JSON: {exc}")
        else:
            from meta_flow.workflow.cr_lifecycle import validate_index_payload

            errors.extend(
                f"CR-INDEX projection invalid: {message}"
                for message in validate_index_payload(index)
            )
            items = [item for item in index.get("items", []) if isinstance(item, dict)]
            if not any(item.get("id") == cr_id for item in items):
                errors.append(f"CR-INDEX missing CR referenced by CP result: {cr_id}")
    state_path = _resolve_runtime_ref(root, "process/state/STATE.current.json")
    if cr_id and state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{state_path} invalid JSON: {exc}")
        else:
            active_change = state.get("active_change")
            if active_change and str(active_change) != cr_id and checkpoint not in {"CP8"}:
                errors.append(
                    f"STATE.current.json active_change={active_change} differs from CP result cr_id={cr_id}"
                )
    return errors


def _candidate_route_plan_paths(root: Path, result: dict[str, Any]) -> list[Path]:
    refs: list[str] = []
    explicit = str(result.get("route_plan_ref") or "")
    if explicit:
        refs.append(explicit.split("#", 1)[0])
    cr_id = str(result.get("cr_id") or "")
    if cr_id:
        refs.extend(
            format_runtime_ref(root, path)
            for path in sorted(
                _resolve_runtime_ref(root, "process/checks").glob(f"CP0-*{cr_id}*.route-plan.json")
            )
            if path.is_file()
        )
    return [_resolve_runtime_path(root, Path(ref)) for ref in refs]


def _validate_post_cp_transition(root: Path, result: dict[str, Any]) -> tuple[list[str], list[str]]:
    checkpoint = str(result.get("checkpoint") or result.get("checkpoint_id") or "")
    decision = str(result.get("decision") or "")
    state_path = _resolve_runtime_ref(root, "process/state/STATE.current.json")
    if not state_path.is_file():
        return [], ["state-transition skipped: STATE.current.json missing"]
    route_paths = _candidate_route_plan_paths(root, result)
    if not route_paths:
        return [], [
            "state-transition skipped: route_plan_ref missing and no CP0 route-plan artifact found"
        ]
    for route_path in route_paths:
        if route_path.is_file():
            return state_transition.validate_transition(
                route_plan_path=route_path,
                state_path=state_path,
                checkpoint=checkpoint,
                decision=decision,
            )
    return [], ["state-transition skipped: route_plan artifact missing"]


def allowed_decisions(checkpoint: str) -> set[str]:
    if checkpoint == "CP7":
        return CP7_DECISIONS
    return GENERAL_DECISIONS


def load_cp_result(path: Path) -> dict[str, Any]:
    return _read_json(path.resolve())


def validate_cp_result(
    result_path: Path,
    *,
    project_root: Path | None = None,
    check_consistency: bool = False,
    correlation_profile: str = "compat",
) -> tuple[list[str], list[str]]:
    root = project_root.resolve() if project_root is not None else Path.cwd().resolve()
    result_path = _resolve_runtime_path(root, result_path)
    if not result_path.is_file():
        return [f"CP result missing: {format_runtime_ref(root, result_path)}"], []
    errors: list[str] = []
    warnings: list[str] = []
    try:
        result = load_cp_result(result_path)
    except ValueError as exc:
        return [str(exc)], []
    if correlation_profile not in {"compat", "audit", "strict"}:
        return ["correlation_profile must be compat, audit or strict"], []

    if result.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    checkpoint = str(result.get("checkpoint") or result.get("checkpoint_id") or "")
    if not CHECKPOINT_RE.fullmatch(checkpoint):
        errors.append(f"checkpoint must be CP0..CP8: {checkpoint or '-'}")
    decision = str(result.get("decision") or "")
    if decision not in allowed_decisions(checkpoint):
        errors.append(f"invalid decision for {checkpoint or 'checkpoint'}: {decision or '-'}")
    for key in ("items", "blockers", "waivers"):
        if key not in result:
            errors.append(f"missing required field: {key}")
    items = result.get("items") or []
    if not isinstance(items, list) or not items:
        errors.append("items must be a non-empty list")
        items = []
    blocking_item_seen = False
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append(f"item {index}: must be an object")
            continue
        for key in ("id", "name", "status", "severity", "evidence_refs"):
            if key not in item:
                errors.append(f"item {index}: missing required field: {key}")
        status = str(item.get("status") or "")
        if status not in ITEM_STATUSES:
            errors.append(f"item {index}: invalid status: {status or '-'}")
        severity = str(item.get("severity") or "")
        if severity not in SEVERITIES:
            errors.append(f"item {index}: invalid severity: {severity or '-'}")
        evidence_refs = item.get("evidence_refs")
        if evidence_refs is not None and not isinstance(evidence_refs, list):
            errors.append(f"item {index}: evidence_refs must be a list")
        if status in {"FAIL", "BLOCKED"} and severity in {"BLOCKER", "HIGH"}:
            blocking_item_seen = True
        if status == "WAIVED" and not item.get("waiver_ref"):
            errors.append(f"item {index}: WAIVED requires waiver_ref")

    blockers = result.get("blockers") or []
    waivers = result.get("waivers") or []
    if not isinstance(blockers, list):
        errors.append("blockers must be a list")
        blockers = []
    if not isinstance(waivers, list):
        errors.append("waivers must be a list")
    if (blocking_item_seen or blockers) and decision in {"PASS", "PASS_WITH_RISK"}:
        errors.append("decision cannot be PASS/PASS_WITH_RISK when blocking items exist")
    if decision == "N/A" and not any(
        result.get(key)
        for key in ("not_applicable_reason", "route_plan_ref", "checkpoint_applicability")
    ):
        errors.append(
            "decision=N/A requires not_applicable_reason, route_plan_ref, or checkpoint_applicability"
        )
    if decision == "WAIVED" and not waivers:
        errors.append("decision=WAIVED requires waivers")
    if checkpoint == "CP2":
        errors.extend(_validate_cp2_commitments(result))
    if checkpoint == "CP7":
        errors.extend(_validate_cp7_alignment(result))
    if checkpoint == "CP8":
        errors.extend(_validate_cp8_fact_diff(result))
    correlation = _correlation_findings(root, result_path, result)
    if correlation_profile == "strict":
        errors.extend(correlation)
    elif correlation_profile == "audit":
        warnings.extend(correlation)
    errors.extend(_validate_checker_provenance(result))
    if checkpoint in {"CP6", "CP7"} and decision != "N/A":
        if not result.get("story_id"):
            errors.append(f"{checkpoint} result requires story_id")
        if not result.get("context_ref"):
            errors.append(f"{checkpoint} result requires context_ref")
        if not result.get("evidence_ref"):
            errors.append(f"{checkpoint} result requires evidence_ref")
        if not result.get("dispatch_refs"):
            errors.append(f"{checkpoint} result requires dispatch_refs")
    deny_refs = _deny_default_refs(result)
    if deny_refs:
        read_expansion_refs = [
            str(item) for item in _as_list(result.get("read_expansion_refs")) if str(item)
        ]
        if not read_expansion_refs:
            errors.append(
                "deny-default references require read_expansion_refs: " + ", ".join(deny_refs)
            )
        elif project_root:
            ledger_events, ledger_errors = read_expansion.load_events(
                read_expansion.default_ledger_path(root)
            )
            if ledger_errors:
                errors.extend(f"read expansion ledger: {error}" for error in ledger_errors)
            event_ids = {str(event.get("event_id") or "") for event in ledger_events}
            requested_paths = {
                str(event.get("requested_path") or "")
                for event in ledger_events
                if event.get("event_id") in read_expansion_refs
            }
            missing_events = sorted(set(read_expansion_refs) - event_ids)
            if missing_events:
                errors.append(
                    "read_expansion_refs missing from READ-EXPANSION-LEDGER: "
                    + ", ".join(missing_events)
                )
            missing_paths = sorted(path for path in deny_refs if path not in requested_paths)
            if missing_paths:
                errors.append(
                    "read_expansion_refs do not cover deny-default refs: "
                    + ", ".join(missing_paths)
                )
    governance_errors, governance_warnings = failure_routing.validate_result_governance(
        root, result
    )
    errors.extend(governance_errors)
    warnings.extend(governance_warnings)
    for ref_key in ("context_ref", "evidence_ref"):
        rel = str(result.get(ref_key) or "")
        if rel and project_root and not _resolve_runtime_path(root, rel).exists():
            warnings.append(f"{ref_key} not found on disk: {rel}")
    if check_consistency and project_root:
        errors.extend(_validate_derived_consistency(root, result_path, result))
        transition_errors, transition_warnings = _validate_post_cp_transition(root, result)
        errors.extend(transition_errors)
        warnings.extend(transition_warnings)
    return errors, warnings


def _summary_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_summary(result: dict[str, Any]) -> str:
    checkpoint = result.get("checkpoint") or result.get("checkpoint_id") or "-"
    story_id = result.get("story_id") or "-"
    cr_id = result.get("cr_id") or "-"
    decision = result.get("decision") or "-"
    lines = [
        f"# {checkpoint} Summary",
        "",
        f"Decision: {decision}",
        f"Story: {story_id}",
        f"CR: {cr_id}",
        f"Context: {result.get('context_ref') or '-'}",
        f"Evidence: {result.get('evidence_ref') or '-'}",
        f"Dispatch: {', '.join(str(item) for item in _as_list(result.get('dispatch_refs'))) or '-'}",
        "",
        "## Blocking Items",
    ]
    release_decision = result.get("release_decision")
    if release_decision:
        lines.insert(3, f"Release Decision: {release_decision}")
    blockers = _as_list(result.get("blockers"))
    if blockers:
        for item in blockers:
            lines.append(f"- {item}")
    else:
        lines.append("None.")
    provenance = result.get("checker_provenance")
    if isinstance(provenance, dict):
        lines.extend(
            [
                "",
                "## Checker Provenance",
                "",
                "| Field | Value |",
                "|---|---|",
                f"| checker_name | {_summary_cell(provenance.get('checker_name'))} |",
                f"| checker_version | {_summary_cell(provenance.get('checker_version'))} |",
                f"| checker_commit | {_summary_cell(provenance.get('checker_commit'))} |",
                f"| invocation | {_summary_cell(provenance.get('invocation'))} |",
                f"| generated_by | {_summary_cell(provenance.get('generated_by'))} |",
                f"| fallback_used | {_summary_cell(provenance.get('fallback_used'))} |",
            ]
        )
        if provenance.get("fallback_used") is True:
            lines.extend(
                [
                    f"| fallback_reason | {_summary_cell(provenance.get('fallback_reason'))} |",
                    f"| fallback_review_ref | {_summary_cell(provenance.get('fallback_review_ref'))} |",
                ]
            )
    lines.extend(
        ["", "## Check Items", "", "| ID | Status | Severity | Name |", "|---|---|---|---|"]
    )
    for item in _as_list(result.get("items")):
        if not isinstance(item, dict):
            continue
        lines.append(
            f"| {item.get('id', '-')} | {item.get('status', '-')} | {item.get('severity', '-')} | {item.get('name', '-')} |"
        )
    fact_diff = result.get("fact_diff")
    if isinstance(fact_diff, list) and fact_diff:
        lines.extend(
            [
                "",
                "## Fact Diff",
                "",
                "| Promise Ref | Promise | Status | Decision Impact | Evidence | Risk |",
                "|---|---|---|---|---|---|",
            ]
        )
        for item in fact_diff:
            if not isinstance(item, dict):
                continue
            evidence_refs = (
                ", ".join(str(ref) for ref in _as_list(item.get("evidence_refs"))) or "-"
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        _summary_cell(item.get("promise_ref")),
                        _summary_cell(item.get("promise")),
                        _summary_cell(item.get("status")),
                        _summary_cell(item.get("decision_impact")),
                        _summary_cell(evidence_refs),
                        _summary_cell(item.get("risk_ref")),
                    ]
                )
                + " |"
            )
    lines.extend(["", "## Next", "", str(result.get("next_route") or "-"), ""])
    return "\n".join(lines)


def render_summary_file(
    result_path: Path,
    *,
    output: Path | None = None,
    project_root: Path | None = None,
) -> Path:
    root = project_root.resolve() if project_root else Path.cwd().resolve()
    result_path = _resolve_runtime_path(root, result_path)
    result = load_cp_result(result_path)
    output_path = (
        _resolve_runtime_path(root, output) if output else result_path.with_suffix(".summary.md")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_summary(result), encoding="utf-8")
    return output_path


def build_checkpoint_event(project_root: Path, result_path: Path) -> dict[str, Any]:
    root = project_root.resolve()
    result_path = _resolve_runtime_path(root, result_path)
    result = load_cp_result(result_path)
    checkpoint = str(result.get("checkpoint") or result.get("checkpoint_id") or "")
    event_id = str(
        result.get("event_id")
        or f"{checkpoint}-{result.get('story_id') or result.get('cr_id') or 'global'}"
    )
    summary_ref = str(result.get("summary_ref") or "")
    summary_path = (
        _resolve_runtime_path(root, summary_ref)
        if summary_ref
        else result_path.with_suffix(".summary.md")
    )
    event = {
        "event_id": event_id,
        "event_type": "checkpoint_result",
        "checkpoint": checkpoint,
        "decision": result.get("decision"),
        "result_ref": format_runtime_ref(root, result_path),
        "summary_ref": format_runtime_ref(root, summary_path),
        "story_id": result.get("story_id"),
        "cr_id": result.get("cr_id"),
        "context_ref": result.get("context_ref"),
        "evidence_ref": result.get("evidence_ref"),
        "dispatch_refs": _as_list(result.get("dispatch_refs")),
        "checker_provenance": result.get("checker_provenance"),
        "checked_at": result.get("checked_at") or now_utc(),
    }
    for field in (
        "revision",
        "supersedes_ref",
        "supersedes_event_id",
        "supersedes_plan_digest",
        "cutover_revision",
    ):
        value = result.get(field)
        if value not in (None, ""):
            event[field] = value
    return event


def preflight_checkpoint_ledger_append(
    project_root: Path,
    *,
    result_path: Path,
    ledger: Path | None = None,
) -> dict[str, Any]:
    """在 ledger mutation 前用 canonical projector 验证 replay 与 current head。"""

    root = project_root.resolve()
    resolved_result_path = _resolve_runtime_path(root, result_path)
    result = load_cp_result(resolved_result_path)
    event = build_checkpoint_event(root, resolved_result_path)
    ledger_path = (
        _resolve_runtime_path(root, ledger)
        if ledger
        else _resolve_runtime_ref(root, CHECKPOINT_LEDGER_REL.as_posix())
    )
    events, ledger_errors = event_ledger.load_events(ledger_path)
    if not ledger_path.is_file():
        events = []
        ledger_errors = []
    if ledger_errors:
        return {
            "decision": "BLOCKED",
            "mutation_count": 0,
            "blockers": [f"CHECKPOINT_LEDGER_INVALID:{error}" for error in ledger_errors],
            "event": event,
            "ledger_path": ledger_path,
        }
    matching_ids = [
        candidate
        for candidate in events
        if str(candidate.get("event_id") or "") == str(event["event_id"])
    ]
    replay = [
        candidate
        for candidate in matching_ids
        if str(candidate.get("result_ref") or "") == str(event["result_ref"])
        and str(candidate.get("decision") or "") == str(event.get("decision") or "")
    ]
    if matching_ids and len(replay) != 1:
        return {
            "decision": "BLOCKED",
            "mutation_count": 0,
            "blockers": ["CHECKPOINT_EVENT_ID_DUPLICATE"],
            "event": event,
            "ledger_path": ledger_path,
        }
    simulated = events if replay else [*events, event]
    refs, ref_findings = checkpoint_projection.required_result_refs(
        simulated,
        cr_id=str(event.get("cr_id") or ""),
        checkpoint=str(event.get("checkpoint") or ""),
    )
    results: dict[str, dict[str, Any]] = {
        str(event["result_ref"]): dict(result),
    }
    load_findings = list(ref_findings)
    for result_ref in refs:
        if result_ref in results:
            continue
        candidate_path = _resolve_runtime_ref(root, result_ref)
        if not candidate_path.is_file():
            load_findings.append(
                checkpoint_projection.CheckpointFindingV1(
                    code="RESULT_FILE_MISSING",
                    message=f"current candidate result 不存在: {result_ref}",
                    cr_id=str(event.get("cr_id") or ""),
                    checkpoint=str(event.get("checkpoint") or ""),
                    result_ref=result_ref,
                )
            )
            continue
        try:
            payload = _read_json(candidate_path)
        except ValueError as exc:
            load_findings.append(
                checkpoint_projection.CheckpointFindingV1(
                    code="RESULT_FILE_INVALID",
                    message=str(exc),
                    cr_id=str(event.get("cr_id") or ""),
                    checkpoint=str(event.get("checkpoint") or ""),
                    result_ref=result_ref,
                )
            )
            continue
        results[result_ref] = payload
    projection = checkpoint_projection.project_checkpoint_events(
        simulated,
        results,
        cr_id=str(event.get("cr_id") or ""),
        checkpoint=str(event.get("checkpoint") or ""),
        load_findings=load_findings,
    )
    if projection.findings:
        return {
            "decision": "BLOCKED",
            "mutation_count": 0,
            "blockers": [f"{finding.code}:{finding.message}" for finding in projection.findings],
            "event": event,
            "ledger_path": ledger_path,
            "projection_digest": projection.as_dict()["projection_digest"],
        }
    return {
        "decision": "NO_CHANGE" if replay else "READY",
        "mutation_count": 0 if replay else 1,
        "blockers": [],
        "event": event,
        "ledger_path": ledger_path,
        "projection_digest": projection.as_dict()["projection_digest"],
    }


def append_checkpoint_ledger(
    project_root: Path, *, result_path: Path, ledger: Path | None = None
) -> Path:
    root = project_root.resolve()
    result_path = _resolve_runtime_path(root, result_path)
    errors, _warnings = validate_cp_result(
        result_path,
        project_root=root,
        check_consistency=False,
        correlation_profile="compat",
    )
    if errors:
        raise ValueError("checkpoint result is invalid; ledger mutation=0: " + "; ".join(errors))
    preflight = preflight_checkpoint_ledger_append(
        root,
        result_path=result_path,
        ledger=ledger,
    )
    if preflight["decision"] == "BLOCKED":
        raise ValueError(
            "checkpoint ledger append blocked; mutation=0: " + "; ".join(preflight["blockers"])
        )
    if preflight["decision"] == "NO_CHANGE":
        return preflight["ledger_path"]
    return event_ledger.append_event(preflight["ledger_path"], preflight["event"])


def build_applicability_aggregate(
    project_root: Path,
    route_plan_path: Path,
    *,
    cr_id: str = "",
) -> dict[str, Any]:
    root = project_root.resolve()
    route_plan_path = _resolve_runtime_path(root, route_plan_path)
    route_plan = _read_json(route_plan_path)
    route_ref = format_runtime_ref(root, route_plan_path)
    return {
        "schema_version": 1,
        "kind": "checkpoint_applicability_aggregate",
        "cr_id": cr_id or str(route_plan.get("cr_id") or ""),
        "source_route_plan_ref": route_ref,
        "checkpoint_applicability": route_plan.get("checkpoint_applicability") or {},
        "stages": route_plan.get("stages") or [],
        "decision": "PASS" if route_plan.get("decision") != "BLOCKED" else "BLOCKED",
        "generated_at": now_utc(),
    }


def write_applicability_aggregate(
    project_root: Path,
    route_plan_path: Path,
    output: Path,
    *,
    cr_id: str = "",
) -> Path:
    root = project_root.resolve()
    aggregate = build_applicability_aggregate(root, route_plan_path, cr_id=cr_id)
    output_path = _resolve_runtime_path(root, output)
    _write_json(output_path, aggregate)
    return output_path


def validate_applicability_aggregate(
    project_root: Path,
    aggregate_path: Path,
) -> tuple[list[str], list[str]]:
    root = project_root.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    aggregate_path = _resolve_runtime_path(root, aggregate_path)
    if not aggregate_path.is_file():
        return [f"applicability aggregate missing: {aggregate_path}"], warnings
    try:
        aggregate = _read_json(aggregate_path)
    except ValueError as exc:
        return [str(exc)], warnings
    if aggregate.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if aggregate.get("kind") != "checkpoint_applicability_aggregate":
        errors.append("kind must be checkpoint_applicability_aggregate")
    route_ref = _ref_path(aggregate.get("source_route_plan_ref"))
    if not route_ref:
        errors.append("source_route_plan_ref is required")
        return errors, warnings
    route_path = _resolve_runtime_path(root, route_ref)
    if not route_path.is_file():
        errors.append(f"source_route_plan_ref missing on disk: {route_ref}")
        return errors, warnings
    try:
        route_plan = _read_json(route_path)
    except ValueError as exc:
        errors.append(str(exc))
        return errors, warnings
    expected = route_plan.get("checkpoint_applicability") or {}
    actual = aggregate.get("checkpoint_applicability") or {}
    if actual != expected:
        errors.append("checkpoint_applicability does not match source route plan")
    if (aggregate.get("stages") or []) != (route_plan.get("stages") or []):
        errors.append("stages do not match source route plan")
    if route_plan.get("decision") == "BLOCKED":
        warnings.append("source route plan decision is BLOCKED")
    return errors, warnings


def _print_cp_help() -> None:
    print(
        "usage: meta-flow cp <result-check|input-hashes|render-summary|ledger-append|applicability-build|applicability-check> [options]\n\n"
        "Commands:\n"
        "  result-check    Validate a machine-readable CP result JSON.\n"
        "  projection      Project canonical checkpoint current heads for one CR.\n"
        "  input-hashes    Build native file-byte digests for CP strict correlation.\n"
        "  render-summary  Render a compact Markdown summary from CP result JSON.\n"
        "  ledger-append   Append a checkpoint_result event to CHECKPOINT-LEDGER.ndjson.\n\n"
        "  applicability-build  Build a CP8 checkpoint applicability aggregate from a route plan.\n"
        "  applicability-check  Validate a CP8 checkpoint applicability aggregate against its route plan.\n\n"
        "Examples:\n"
        "  meta-flow cp result-check --result process/checks/CP6-STORY.result.json --project-root .\n"
        "  meta-flow cp projection --project-root . --cr-id CR-063 --checkpoint CP5 --format json\n"
        "  meta-flow cp input-hashes --project-root . --ref process/returns/STORY.CP6.return.json --ref process/evidence/STORY.CP6.index.json\n"
        "  meta-flow cp result-check --result process/checks/CP6-STORY.result.json --project-root . --mode silent\n"
        "  meta-flow cp result-check --result process/checks/CP8-CR.result.json --project-root . --check-consistency\n"
        "  meta-flow cp render-summary --result process/checks/CP6-STORY.result.json\n"
        "  meta-flow cp ledger-append --result process/checks/CP6-STORY.result.json --project-root .\n"
        "  meta-flow cp applicability-build --route-plan process/checks/CP0-CR156.route-plan.json --output process/checks/CP8-CR156.applicability.json --project-root .\n"
        "  meta-flow cp applicability-check --aggregate process/checks/CP8-CR156.applicability.json --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_cp_help()
        return 0
    command = args[0]
    if command == "result-check":
        parser = argparse.ArgumentParser(prog="meta-flow cp result-check")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--result", dest="result_path", type=Path, required=True)
        parser.add_argument("--check-consistency", action="store_true")
        parser.add_argument("--correlation-profile", choices=("audit", "strict"), default="audit")
        parser.add_argument("--mode", choices=("normal", "silent", "verbose"), default="normal")
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_cp_result(
            parsed.result_path,
            project_root=parsed.project_root,
            check_consistency=parsed.check_consistency,
            correlation_profile=parsed.correlation_profile,
        )
        if parsed.mode == "silent":
            if errors:
                print("FAIL: " + "; ".join(errors))
            else:
                print("PASS")
            return 1 if errors else 0
        print("CP Result Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "input-hashes":
        parser = argparse.ArgumentParser(prog="meta-flow cp input-hashes")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--ref", dest="refs", action="append", default=[])
        parsed = parser.parse_args(args[1:])
        try:
            payload = build_input_artifact_hashes(parsed.project_root, parsed.refs)
        except ValueError as exc:
            print("CP Input Hashes: BLOCKED")
            print(f"- {exc}")
            return 2
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "projection":
        parser = argparse.ArgumentParser(prog="meta-flow cp projection")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--cr-id", required=True)
        parser.add_argument("--checkpoint", default="")
        parser.add_argument("--format", choices=("json",), default="json")
        parsed = parser.parse_args(args[1:])
        try:
            projection = checkpoint_projection.load_checkpoint_projection(
                parsed.project_root,
                cr_id=parsed.cr_id,
                checkpoint=parsed.checkpoint,
            )
        except (OSError, ProcessRouteError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "CheckpointProjectionV1",
                        "decision": "BLOCKED",
                        "target_cr_id": parsed.cr_id,
                        "target_checkpoint": parsed.checkpoint.upper(),
                        "findings": [
                            {
                                "code": "PROJECTION_INPUT_BLOCKED",
                                "message": str(exc).replace(
                                    str(parsed.project_root.resolve()),
                                    "<release-root>",
                                ),
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
        print(
            json.dumps(
                projection.as_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if projection.decision == "PASS" else 2
    if command == "render-summary":
        parser = argparse.ArgumentParser(prog="meta-flow cp render-summary")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--result", dest="result_path", type=Path, required=True)
        parser.add_argument("--output", type=Path, default=None)
        parsed = parser.parse_args(args[1:])
        path = render_summary_file(
            parsed.result_path,
            output=parsed.output,
            project_root=parsed.project_root,
        )
        print(f"wrote: {format_runtime_ref(parsed.project_root, path)}")
        return 0
    if command == "ledger-append":
        parser = argparse.ArgumentParser(prog="meta-flow cp ledger-append")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--result", dest="result_path", type=Path, required=True)
        parser.add_argument("--ledger", type=Path, default=None)
        parsed = parser.parse_args(args[1:])
        try:
            preflight = preflight_checkpoint_ledger_append(
                parsed.project_root,
                result_path=parsed.result_path,
                ledger=parsed.ledger,
            )
            if preflight["decision"] == "BLOCKED":
                print("Checkpoint Ledger Append: BLOCKED")
                for blocker in preflight["blockers"]:
                    print(f"- {blocker}")
                return 2
            path = append_checkpoint_ledger(
                parsed.project_root,
                result_path=parsed.result_path,
                ledger=parsed.ledger,
            )
        except (OSError, ProcessRouteError, ValueError) as exc:
            print("Checkpoint Ledger Append: BLOCKED")
            print(f"- {exc}")
            return 2
        if preflight["decision"] == "NO_CHANGE":
            print(
                "Checkpoint Ledger Append: NO_CHANGE "
                f"({format_runtime_ref(parsed.project_root, path)})"
            )
            return 0
        print(f"appended: {format_runtime_ref(parsed.project_root, path)}")
        return 0
    if command == "applicability-build":
        parser = argparse.ArgumentParser(prog="meta-flow cp applicability-build")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--route-plan", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--cr-id", default="")
        parsed = parser.parse_args(args[1:])
        path = write_applicability_aggregate(
            parsed.project_root,
            parsed.route_plan,
            parsed.output,
            cr_id=parsed.cr_id,
        )
        print(f"wrote: {format_runtime_ref(parsed.project_root, path)}")
        return 0
    if command == "applicability-check":
        parser = argparse.ArgumentParser(prog="meta-flow cp applicability-check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--aggregate", type=Path, required=True)
        parser.add_argument("--mode", choices=("normal", "silent", "verbose"), default="normal")
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_applicability_aggregate(parsed.project_root, parsed.aggregate)
        if parsed.mode == "silent":
            if errors:
                print("FAIL: " + "; ".join(errors))
            else:
                print("PASS")
            return 1 if errors else 0
        print("CP Applicability Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 cp 命令: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
