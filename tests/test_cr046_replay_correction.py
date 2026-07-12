from __future__ import annotations

import json
import tempfile
import hashlib
import unittest
from pathlib import Path

from meta_flow.checks.audit_report import build_audit_report
from meta_flow.checks.correction import append_correction, replay_corrections, validate_correction_event
from meta_flow.evidence.pilot_adapter import build_pilot_manifest, preflight_pilot
from meta_flow.evidence.replay import admission_requires_reprobe, legacy_profile_annotation, replay_outcome
from meta_flow.evidence.platform_contract import CapabilityProbe
from datetime import datetime, timedelta, timezone


class ReplayCorrectionTests(unittest.TestCase):
    def test_audit_report_counts_rows_attempts_threads_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "process/state/AGENT-DISPATCH-LEDGER.ndjson"
            ledger.parent.mkdir(parents=True)
            ledger.write_text("\n".join(json.dumps(item) for item in (
                {"event_id":"e1","event_type":"dispatch","dispatch_id":"d1","attempt_id":"a1","thread_id":"t1","cr_id":"CR-X","status":"running"},
                {"event_id":"e2","event_type":"dispatch","dispatch_id":"d1","attempt_id":"a1","thread_id":"t1","cr_id":"CR-X","status":"completed"},
            )) + "\n", encoding="utf-8")
            report = build_audit_report(root, cr_id="CR-X")
        self.assertEqual({"event_rows": 2, "attempts": 1, "threads": 1, "terminal_events": 1}, report["counts"])

    def test_correction_requires_append_only_audit_fields(self) -> None:
        event = {"schema_version":"meta-flow.correction/v1","event_id":"C1","target_ref":{"namespace":"checkpoint","id":"CP7","source_sha256":"sha256:x"},"patch":[{"op":"add","path":"/annotations/review_note","value":"precision"}],"reason":"precision","author":"auditor","evidence_refs":["e"],"created_at":"2026-07-12T00:00:00Z","historical_mutation":False}
        self.assertEqual([], validate_correction_event(event))
        self.assertIn("historical_mutation must be false; corrections are append-only", validate_correction_event({**event, "historical_mutation": True}))

    def test_correction_append_replay_preserves_original(self) -> None:
        event = {"schema_version":"meta-flow.correction/v1","event_id":"C1","target_ref":{"namespace":"checkpoint","id":"CP7","source_sha256":"sha256:x"},"patch":[{"op":"add","path":"/annotations/review_note","value":"precision"}],"reason":"precision","author":"auditor","evidence_refs":["e"],"created_at":"2026-07-12T00:00:00Z"}
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "CORRECTION-LEDGER.ndjson"
            empty_hash = "sha256:" + hashlib.sha256(b"").hexdigest()
            receipt = append_correction(ledger, event, expected_prefix_hash=empty_hash)
        self.assertEqual("C1", receipt["event_id"])
        original = {"decision": "PASS"}
        effective = replay_corrections(original, [event])
        self.assertEqual({"decision": "PASS"}, original)
        self.assertEqual("precision", effective["annotations"]["review_note"])

    def test_replay_and_legacy_profile_never_upgrade_proof(self) -> None:
        outcome = replay_outcome({"decision":"PASS","checker_provenance":None}, current_checker="meta-flow", current_commit="x")
        self.assertEqual("unavailable", outcome.as_executed)
        annotation = legacy_profile_annotation({"codex_agent_name":"meta-qa-critical"})
        self.assertEqual("D3-self-declared-unverifiable", annotation["evidence_class"])
        self.assertIsNone(annotation["resolved_model"])

    def test_freshness_and_dry_run_pilot_are_fail_closed(self) -> None:
        now = datetime.now(timezone.utc)
        probe = CapabilityProbe("d0", "s", "e", now, now + timedelta(seconds=10), "h", "v1", "0", "platform-reported", "receipt")
        admission = admission_requires_reprobe(probe, now=now, session_id="different", session_epoch="e", config_sha256="h", selector_schema_version="v1", reload_generation="0")
        self.assertTrue(admission["reprobe_required"])
        manifest = build_pilot_manifest(targets=[f"target-{i}" for i in range(23)], authorization_ref=None, checker_provenance={"checker_name":"test"})
        self.assertEqual("PASS", preflight_pilot(manifest, project_root=Path("."))["decision"])


if __name__ == "__main__":
    unittest.main()
