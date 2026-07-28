from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from meta_flow.evidence.dispatch import (
    DispatchAttempt,
    ThreadRuntimeIdentity,
    advance_attempt,
    validate_attempt_graph,
)
from meta_flow.evidence.platform_contract import (
    CapabilityProbe,
    ProfileConfig,
    SpawnReceiptEvidence,
    SpawnRequestEvidence,
    admit_reuse,
    classify_discovery,
    decide_profile_fallback,
    load_profile_config,
    needs_reprobe,
    verify_spawn,
)
from meta_flow.state import event_ledger

NOW = datetime(2026, 7, 12, 4, 40, tzinfo=UTC)


def dispatch_attempt(
    dispatch_id: str,
    attempt_id: str,
    status: str,
    source_ref: str,
    **overrides: object,
) -> DispatchAttempt:
    data: dict[str, object] = {
        "dispatch_id": dispatch_id,
        "attempt_id": attempt_id,
        "status": status,
        "source_ref": source_ref,
        "event_id": f"event-{dispatch_id}-{attempt_id}-{status}",
        "story_id": "STORY-CR046-S01",
        "canonical_role": "meta-dev",
        "checkpoint": "CP6",
        "dispatch_mode": "subagent",
    }
    data.update(overrides)
    return DispatchAttempt(**data)  # type: ignore[arg-type]


def config() -> ProfileConfig:
    return ProfileConfig("meta-qa-critical", "cfg-1", "gpt-5.6-sol", "xhigh", ".codex/agents/meta-qa-critical.toml")


def probe(**overrides: object) -> CapabilityProbe:
    data: dict[str, object] = {
        "capability_id": "cap-1",
        "session_id": "session-1",
        "session_epoch": "epoch-1",
        "observed_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=5),
        "config_sha256": "cfg-1",
        "selector_schema_version": "v1",
        "reload_generation": "reload-1",
        "source": "platform-reported",
        "source_ref": "platform:cap-1",
    }
    data.update(overrides)
    return CapabilityProbe(**data)  # type: ignore[arg-type]


def request(**overrides: object) -> SpawnRequestEvidence:
    data: dict[str, object] = {
        "dispatch_id": "dispatch-1",
        "attempt_id": "attempt-1",
        "requested_profile": "meta-qa-critical",
        "config_sha256": "cfg-1",
        "requirement": "required",
        "capability_id": "cap-1",
        "selector_present": True,
        "source_ref": "request:attempt-1",
    }
    data.update(overrides)
    return SpawnRequestEvidence(**data)  # type: ignore[arg-type]


def receipt(**overrides: object) -> SpawnReceiptEvidence:
    data: dict[str, object] = {
        "receipt_id": "receipt-1",
        "dispatch_id": "dispatch-1",
        "attempt_id": "attempt-1",
        "thread_id": "thread-1",
        "agent_id": "agent-1",
        "session_id": "session-1",
        "session_epoch": "epoch-1",
        "resolved_profile": "meta-qa-critical",
        "config_sha256": "cfg-1",
        "resolved_model": "gpt-5.6-sol",
        "resolved_reasoning_effort": "xhigh",
        "source": "platform-reported",
        "source_ref": "platform:receipt-1",
    }
    data.update(overrides)
    return SpawnReceiptEvidence(**data)  # type: ignore[arg-type]


class DispatchAttestationTests(unittest.TestCase):
    def test_pc01_d2_config_is_not_d0_discovery(self) -> None:
        result = classify_discovery(config(), None, now=NOW, session_id="session-1", session_epoch="epoch-1", selector_schema_version="v1", reload_generation="reload-1")
        self.assertEqual("CONFIG_VALIDATED", result.state)
        self.assertEqual("D0_UNAVAILABLE", result.findings[0].code)

    def test_pc02_untrusted_probe_cannot_discover(self) -> None:
        result = classify_discovery(config(), probe(source="ledger-declared"), now=NOW, session_id="session-1", session_epoch="epoch-1", selector_schema_version="v1", reload_generation="reload-1")
        self.assertEqual("CONFIG_VALIDATED", result.state)
        self.assertEqual("D0_UNTRUSTED_SOURCE", result.findings[0].code)

    def test_pc03_fresh_platform_probe_discovers(self) -> None:
        result = classify_discovery(config(), probe(), now=NOW, session_id="session-1", session_epoch="epoch-1", selector_schema_version="v1", reload_generation="reload-1")
        self.assertEqual("PROFILE_DISCOVERED", result.state)
        self.assertEqual((), result.findings)

    def test_pc04_explicit_selector_is_required(self) -> None:
        result = verify_spawn(request(selector_present=False), receipt(), config(), probe(), now=NOW)
        self.assertEqual("BLOCKED", result.decision)
        self.assertIn("MISSING_EXPLICIT_SELECTOR", [item.code for item in result.findings])

    def test_pc05_missing_receipt_is_fail_closed_for_required_profile(self) -> None:
        result = verify_spawn(request(), None, config(), probe(), now=NOW)
        self.assertEqual("BLOCKED", result.decision)
        self.assertFalse(result.axes.custom_agent_verified)
        self.assertIn("MISSING_SPAWN_RECEIPT", [item.code for item in result.findings])

    def test_pc06_valid_spawn_freezes_thread_identity(self) -> None:
        result = verify_spawn(request(), receipt(), config(), probe(), now=NOW)
        self.assertEqual("ALLOW_SPAWN", result.decision)
        self.assertTrue(result.axes.custom_agent_verified)
        self.assertEqual("thread-1", result.thread_identity.thread_id if result.thread_identity else "")

    def test_pc07_receipt_profile_mismatch_is_rejected(self) -> None:
        result = verify_spawn(request(), receipt(resolved_profile="meta-qa"), config(), probe(), now=NOW)
        self.assertEqual("BLOCKED", result.decision)
        self.assertIn("SPAWN_RECEIPT_MISMATCH", [item.code for item in result.findings])

    def test_pc08_receipt_hash_mismatch_is_rejected(self) -> None:
        result = verify_spawn(request(), receipt(config_sha256="cfg-other"), config(), probe(), now=NOW)
        self.assertEqual("BLOCKED", result.decision)
        self.assertIn("SPAWN_RECEIPT_MISMATCH", [item.code for item in result.findings])

    def test_pc09_preferred_profile_can_be_degraded_only_with_approval(self) -> None:
        blocked, _ = decide_profile_fallback(requirement="preferred", evidence_available=False, user_approved=False)
        degraded, findings = decide_profile_fallback(requirement="preferred", evidence_available=False, user_approved=True)
        self.assertEqual("BLOCKED", blocked)
        self.assertEqual("DEGRADED_UNATTESTED", degraded)
        self.assertEqual("PREFERRED_PROFILE_DEGRADED", findings[0].code)

    def test_pc10_required_profile_never_degrades(self) -> None:
        decision, findings = decide_profile_fallback(requirement="required", evidence_available=False, user_approved=True)
        self.assertEqual("BLOCKED", decision)
        self.assertEqual("REQUIRED_PROFILE_UNAVAILABLE", findings[0].code)

    def test_pc11_attempt_terminal_cannot_reopen(self) -> None:
        attempt = dispatch_attempt(
            "dispatch-1",
            "attempt-1",
            "completed",
            "event:completed",
            terminal_result="PASS",
        )
        transition = advance_attempt(attempt, {"status": "running"})
        self.assertIn("ATTEMPT_ALREADY_TERMINAL", [item.code for item in transition.findings])

    def test_pc12_valid_reuse_receipt_inherits_same_identity(self) -> None:
        verification = verify_spawn(request(), receipt(), config(), probe(), now=NOW)
        self.assertIsNotNone(verification.thread_identity)
        result = admit_reuse(verification.thread_identity, request(dispatch_id="dispatch-2", attempt_id="attempt-2"), receipt(dispatch_id="dispatch-2", attempt_id="attempt-2"))
        self.assertEqual("ALLOW_REUSE", result.decision)
        self.assertTrue(result.axes.model_attested)

    def test_pc13_profile_upgrade_requires_new_spawn(self) -> None:
        thread = ThreadRuntimeIdentity("thread-1", "agent-1", "receipt-1", "meta-dev", "cfg-dev", "gpt-5.6-terra", "medium", "session-1", "epoch-1", "receipt:dev")
        result = admit_reuse(thread, request(requested_profile="meta-qa-critical", config_sha256="cfg-1"), None)
        self.assertEqual("NEW_SPAWN_REQUIRED", result.decision)
        self.assertEqual("NEW_SPAWN_REQUIRED", result.findings[0].code)

    def test_pc14_attempt_identity_collision_is_rejected(self) -> None:
        attempts = [
            dispatch_attempt("dispatch-1", "attempt-1", "completed", "first", terminal_result="PASS"),
            dispatch_attempt("dispatch-2", "attempt-1", "completed", "second", terminal_result="PASS"),
        ]
        self.assertIn("CROSS_DISPATCH_ATTEMPT_ID", [item.code for item in validate_attempt_graph(attempts)])

    def test_pc15_attempt_supersedes_cycle_is_rejected(self) -> None:
        attempts = [
            dispatch_attempt(
                "dispatch-1",
                "a",
                "superseded",
                "a",
                terminal_result="SUPERSEDED",
                supersedes_attempt_id="b",
            ),
            dispatch_attempt(
                "dispatch-1",
                "b",
                "superseded",
                "b",
                terminal_result="SUPERSEDED",
                supersedes_attempt_id="a",
            ),
        ]
        self.assertIn("SUPERSEDES_CYCLE", [item.code for item in validate_attempt_graph(attempts)])

    def test_pc16_missing_terminal_closure_is_rejected(self) -> None:
        findings = validate_attempt_graph(
            [dispatch_attempt("dispatch-1", "attempt-1", "running", "event:running")]
        )
        self.assertIn("MISSING_TERMINAL_CLOSURE", [item.code for item in findings])

    def test_public_dispatch_attempt_is_typed_contract_adapter(self) -> None:
        attempt = dispatch_attempt(
            "dispatch-1",
            "attempt-1",
            "completed",
            "event:completed",
            terminal_result="PASS",
        )

        typed, errors = attempt.as_typed_attempt()

        self.assertEqual((), errors)
        self.assertIsInstance(typed, event_ledger.TypedDispatchAttemptV1)
        self.assertEqual("meta-dev", typed.canonical_role if typed else "")

    def test_inline_fallback_adapter_requires_approval(self) -> None:
        attempt = dispatch_attempt(
            "dispatch-1",
            "attempt-1",
            "completed",
            "event:inline",
            terminal_result="PASS",
            dispatch_mode="inline-fallback",
            approval_ref="",
        )

        _typed, errors = attempt.as_typed_attempt()

        self.assertIn("MISSING_INLINE_FALLBACK_APPROVAL", errors)

    def test_pc17_config_loader_produces_d2_hash_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.toml"
            path.write_text('name = "meta-doc"\nmodel = "gpt-5.6-luna"\nmodel_reasoning_effort = "low"\n', encoding="utf-8")
            loaded = load_profile_config(path)
        self.assertEqual("meta-doc", loaded.profile)
        self.assertTrue(loaded.valid)
        self.assertEqual(64, len(loaded.config_sha256))

    def test_pc18_each_freshness_trigger_requires_reprobe(self) -> None:
        cases = (
            {"now": NOW + timedelta(minutes=6)},
            {"session_id": "session-2"},
            {"session_epoch": "epoch-2"},
            {"config_sha256": "cfg-2"},
            {"selector_schema_version": "v2"},
            {"reload_generation": "reload-2"},
        )
        for patch in cases:
            with self.subTest(patch=patch):
                stale, reasons = needs_reprobe(
                    probe(),
                    now=patch.get("now", NOW),
                    session_id=patch.get("session_id", "session-1"),
                    session_epoch=patch.get("session_epoch", "epoch-1"),
                    config_sha256=patch.get("config_sha256", "cfg-1"),
                    selector_schema_version=patch.get("selector_schema_version", "v1"),
                    reload_generation=patch.get("reload_generation", "reload-1"),
                )
                self.assertTrue(stale)
                self.assertEqual(1, len(reasons))

    def test_pc19_followup_without_reuse_receipt_does_not_inherit_attestation(self) -> None:
        verification = verify_spawn(request(), receipt(), config(), probe(), now=NOW)
        self.assertIsNotNone(verification.thread_identity)
        result = admit_reuse(verification.thread_identity, request(dispatch_id="dispatch-2", attempt_id="attempt-2"), None)
        self.assertEqual("DEGRADED_UNATTESTED", result.decision)
        self.assertFalse(result.axes.custom_agent_verified)
        self.assertFalse(result.axes.model_attested)
        self.assertEqual("MISSING_REUSE_RECEIPT", result.findings[0].code)

    def test_event_ledger_keeps_event_and_dispatch_identity_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "AGENT-DISPATCH-LEDGER.ndjson"
            for event in (
                {"event_id": "event-running", "event_type": "dispatch", "dispatch_id": "dispatch-1", "attempt_id": "attempt-1", "story_id": "STORY-CR046-S01", "checkpoint": "CP6", "dispatch_mode": "subagent", "canonical_role": "meta-dev", "tool_name": "spawn_agent", "dispatch_trigger": "phase-default", "agent_id": "agent-1", "status": "running", "spawned_at": "2026-07-12T00:00:00Z"},
                {"event_id": "event-completed", "event_type": "dispatch", "dispatch_id": "dispatch-1", "attempt_id": "attempt-1", "story_id": "STORY-CR046-S01", "checkpoint": "CP6", "dispatch_mode": "subagent", "canonical_role": "meta-dev", "tool_name": "spawn_agent", "status": "completed", "terminal_result": "PASS", "completed_at": "2026-07-12T00:01:00Z"},
            ):
                event_ledger.append_event(ledger, event)
            errors, warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_event_ledger_rejects_typed_attempt_without_terminal_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "AGENT-DISPATCH-LEDGER.ndjson"
            event_ledger.append_event(
                ledger,
                {"event_id": "event-running", "event_type": "dispatch", "dispatch_id": "dispatch-1", "attempt_id": "attempt-1", "story_id": "STORY-CR046-S01", "checkpoint": "CP6", "dispatch_mode": "subagent", "canonical_role": "meta-dev", "tool_name": "spawn_agent", "status": "running", "created_at": "2026-07-12T00:00:00Z"},
            )
            errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
        self.assertIn("dispatch dispatch-1 attempt attempt-1: missing terminal closure", errors)


if __name__ == "__main__":
    unittest.main()
