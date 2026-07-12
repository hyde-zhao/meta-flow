"""Fail-closed adapter for custom-agent discovery, request, receipt and reuse."""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dispatch import EvidenceFinding, ThreadRuntimeIdentity, validate_thread_identity_change


FRESHNESS_CODES = (
    "CAPABILITY_EXPIRED",
    "SESSION_CHANGED",
    "SESSION_EPOCH_CHANGED",
    "CONFIG_HASH_CHANGED",
    "SELECTOR_SCHEMA_CHANGED",
    "EXPLICIT_RELOAD",
)


@dataclass(frozen=True)
class ProfileConfig:
    profile: str
    config_sha256: str
    model: str
    reasoning_effort: str
    source_ref: str
    valid: bool = True


@dataclass(frozen=True)
class CapabilityProbe:
    capability_id: str
    session_id: str
    session_epoch: str
    observed_at: datetime | None
    expires_at: datetime | None
    config_sha256: str
    selector_schema_version: str
    reload_generation: str
    source: str
    source_ref: str


@dataclass(frozen=True)
class SpawnRequestEvidence:
    dispatch_id: str
    attempt_id: str
    requested_profile: str
    config_sha256: str
    requirement: str
    capability_id: str | None
    selector_present: bool
    source_ref: str


@dataclass(frozen=True)
class SpawnReceiptEvidence:
    receipt_id: str
    dispatch_id: str
    attempt_id: str
    thread_id: str
    agent_id: str | None
    session_id: str
    session_epoch: str
    resolved_profile: str
    config_sha256: str
    resolved_model: str
    resolved_reasoning_effort: str
    source: str
    source_ref: str


@dataclass(frozen=True)
class AttestationAxes:
    execution_completed: bool
    custom_agent_verified: bool
    model_attested: bool
    attestation_level: str


@dataclass(frozen=True)
class DiscoveryResult:
    state: str
    findings: tuple[EvidenceFinding, ...]


@dataclass(frozen=True)
class SpawnVerification:
    decision: str
    axes: AttestationAxes
    thread_identity: ThreadRuntimeIdentity | None
    findings: tuple[EvidenceFinding, ...]


@dataclass(frozen=True)
class ReuseDecision:
    decision: str
    axes: AttestationAxes
    findings: tuple[EvidenceFinding, ...]


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)


def _finding(code: str, ref: str, field: str, message: str, *refs: str) -> EvidenceFinding:
    return EvidenceFinding(code=code, object_ref=ref, field=field, message=message, source_refs=tuple(item for item in refs if item))


def load_profile_config(path: Path) -> ProfileConfig:
    """Validate a D2 TOML config without treating it as runtime discovery."""

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    profile = str(data.get("name") or path.stem)
    model = str(data.get("model") or "")
    effort = str(data.get("model_reasoning_effort") or "")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ProfileConfig(profile, digest, model, effort, path.as_posix(), bool(profile and model and effort))


def needs_reprobe(
    probe: CapabilityProbe | None,
    *,
    now: datetime | None,
    session_id: str,
    session_epoch: str,
    config_sha256: str,
    selector_schema_version: str,
    reload_generation: str,
) -> tuple[bool, tuple[str, ...]]:
    if probe is None:
        return True, ("CAPABILITY_UNAVAILABLE",)
    reasons: list[str] = []
    current = _now(now)
    if probe.expires_at is None or current >= _now(probe.expires_at):
        reasons.append("CAPABILITY_EXPIRED")
    if probe.session_id != session_id:
        reasons.append("SESSION_CHANGED")
    if probe.session_epoch != session_epoch:
        reasons.append("SESSION_EPOCH_CHANGED")
    if probe.config_sha256 != config_sha256:
        reasons.append("CONFIG_HASH_CHANGED")
    if probe.selector_schema_version != selector_schema_version:
        reasons.append("SELECTOR_SCHEMA_CHANGED")
    if probe.reload_generation != reload_generation:
        reasons.append("EXPLICIT_RELOAD")
    return bool(reasons), tuple(reasons)


def classify_discovery(
    config: ProfileConfig,
    probe: CapabilityProbe | None,
    *,
    now: datetime | None,
    session_id: str,
    session_epoch: str,
    selector_schema_version: str,
    reload_generation: str,
) -> DiscoveryResult:
    if not config.valid:
        return DiscoveryResult("CONFIG_INVALID", (_finding("CONFIG_INVALID", config.source_ref, "config", "profile config is incomplete"),))
    if probe is None:
        return DiscoveryResult("CONFIG_VALIDATED", (_finding("D0_UNAVAILABLE", config.source_ref, "probe", "D2 config is not D0 platform discovery"),))
    stale, reasons = needs_reprobe(
        probe,
        now=now,
        session_id=session_id,
        session_epoch=session_epoch,
        config_sha256=config.config_sha256,
        selector_schema_version=selector_schema_version,
        reload_generation=reload_generation,
    )
    if probe.source != "platform-reported":
        return DiscoveryResult("CONFIG_VALIDATED", (_finding("D0_UNTRUSTED_SOURCE", probe.source_ref, "source", "only platform-reported probe can discover a profile"),))
    if stale:
        return DiscoveryResult(
            "STALE",
            tuple(_finding(code, probe.source_ref, "freshness", "capability probe must be refreshed before spawn") for code in reasons),
        )
    return DiscoveryResult("PROFILE_DISCOVERED", ())


def verify_spawn(
    request: SpawnRequestEvidence,
    receipt: SpawnReceiptEvidence | None,
    config: ProfileConfig,
    probe: CapabilityProbe | None,
    *,
    now: datetime | None,
) -> SpawnVerification:
    findings: list[EvidenceFinding] = []
    discovery = classify_discovery(
        config,
        probe,
        now=now,
        session_id=probe.session_id if probe else "",
        session_epoch=probe.session_epoch if probe else "",
        selector_schema_version=probe.selector_schema_version if probe else "",
        reload_generation=probe.reload_generation if probe else "",
    )
    findings.extend(discovery.findings)
    if not request.selector_present:
        findings.append(_finding("MISSING_EXPLICIT_SELECTOR", request.source_ref, "selector_present", "requested profile must be passed through a platform selector"))
    if request.requested_profile != config.profile:
        findings.append(_finding("REQUEST_CONFIG_PROFILE_MISMATCH", request.source_ref, "requested_profile", "requested profile differs from D2 config", config.source_ref))
    if request.config_sha256 != config.config_sha256:
        findings.append(_finding("REQUEST_CONFIG_HASH_MISMATCH", request.source_ref, "config_sha256", "request config hash differs from D2 config", config.source_ref))
    if not request.capability_id or not probe or request.capability_id != probe.capability_id:
        findings.append(_finding("CAPABILITY_CORRELATION_MISMATCH", request.source_ref, "capability_id", "spawn request must bind the fresh D0 capability probe"))
    if receipt is None:
        findings.append(_finding("MISSING_SPAWN_RECEIPT", request.source_ref, "receipt", "platform receipt is required for verified custom agent dispatch"))
    else:
        if receipt.source != "platform-reported":
            findings.append(_finding("UNTRUSTED_SPAWN_RECEIPT", receipt.source_ref, "source", "receipt must be platform-reported"))
        for field, expected, actual in (
            ("dispatch_id", request.dispatch_id, receipt.dispatch_id),
            ("attempt_id", request.attempt_id, receipt.attempt_id),
            ("resolved_profile", request.requested_profile, receipt.resolved_profile),
            ("config_sha256", config.config_sha256, receipt.config_sha256),
        ):
            if expected != actual:
                findings.append(_finding("SPAWN_RECEIPT_MISMATCH", receipt.source_ref, field, f"receipt {field} differs from request/config", request.source_ref))
        if not receipt.receipt_id or not receipt.thread_id or not receipt.resolved_model or not receipt.resolved_reasoning_effort:
            findings.append(_finding("INCOMPLETE_SPAWN_RECEIPT", receipt.source_ref, "receipt", "receipt lacks immutable runtime identity fields"))
    verified = not findings and receipt is not None and discovery.state == "PROFILE_DISCOVERED"
    axes = AttestationAxes(False, verified, verified, "platform-attested" if verified else "unavailable")
    identity = None
    if verified and receipt is not None:
        identity = ThreadRuntimeIdentity(
            thread_id=receipt.thread_id,
            agent_id=receipt.agent_id,
            spawn_receipt_id=receipt.receipt_id,
            resolved_profile=receipt.resolved_profile,
            config_sha256=receipt.config_sha256,
            resolved_model=receipt.resolved_model,
            resolved_reasoning_effort=receipt.resolved_reasoning_effort,
            session_id=receipt.session_id,
            session_epoch=receipt.session_epoch,
            source_ref=receipt.source_ref,
        )
    if verified:
        decision = "ALLOW_SPAWN"
    elif request.requirement == "required":
        decision = "BLOCKED"
    else:
        decision = "DEGRADED_UNATTESTED"
    return SpawnVerification(decision, axes, identity, tuple(findings))


def admit_reuse(
    thread: ThreadRuntimeIdentity,
    followup_request: SpawnRequestEvidence,
    reuse_receipt: SpawnReceiptEvidence | None,
) -> ReuseDecision:
    identity_findings = validate_thread_identity_change(
        thread,
        requested_profile=followup_request.requested_profile,
        config_sha256=followup_request.config_sha256,
    )
    if identity_findings:
        return ReuseDecision("NEW_SPAWN_REQUIRED", AttestationAxes(False, False, False, "unavailable"), tuple(identity_findings))
    if reuse_receipt is None:
        finding = _finding("MISSING_REUSE_RECEIPT", followup_request.source_ref, "reuse_receipt", "followup cannot inherit profile/model attestation without a bound reuse receipt", thread.source_ref)
        return ReuseDecision("DEGRADED_UNATTESTED", AttestationAxes(False, False, False, "session-observed"), (finding,))
    fields = (
        ("thread_id", thread.thread_id, reuse_receipt.thread_id),
        ("resolved_profile", thread.resolved_profile, reuse_receipt.resolved_profile),
        ("config_sha256", thread.config_sha256, reuse_receipt.config_sha256),
        ("resolved_model", thread.resolved_model, reuse_receipt.resolved_model),
        ("resolved_reasoning_effort", thread.resolved_reasoning_effort, reuse_receipt.resolved_reasoning_effort),
    )
    findings = [
        _finding("REUSE_RECEIPT_MISMATCH", reuse_receipt.source_ref, field, "reuse receipt differs from immutable thread identity", thread.source_ref)
        for field, expected, actual in fields
        if expected != actual
    ]
    if reuse_receipt.source != "platform-reported":
        findings.append(_finding("UNTRUSTED_REUSE_RECEIPT", reuse_receipt.source_ref, "source", "reuse receipt must be platform-reported"))
    if findings:
        return ReuseDecision("NEW_SPAWN_REQUIRED", AttestationAxes(False, False, False, "unavailable"), tuple(findings))
    return ReuseDecision("ALLOW_REUSE", AttestationAxes(False, True, True, "platform-attested"), ())


def decide_profile_fallback(*, requirement: str, evidence_available: bool, user_approved: bool) -> tuple[str, tuple[EvidenceFinding, ...]]:
    if evidence_available:
        return "ALLOW", ()
    if requirement == "required":
        return "BLOCKED", (_finding("REQUIRED_PROFILE_UNAVAILABLE", "dispatch-admission", "requirement", "required profile lacks discovery/selector/receipt"),)
    if requirement == "preferred" and user_approved:
        return "DEGRADED_UNATTESTED", (_finding("PREFERRED_PROFILE_DEGRADED", "dispatch-admission", "requirement", "user approved unattested fallback"),)
    return "BLOCKED", (_finding("FALLBACK_APPROVAL_REQUIRED", "dispatch-admission", "user_approved", "preferred unattested fallback requires explicit user approval"),)
