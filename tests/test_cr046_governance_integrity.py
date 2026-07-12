import json
from pathlib import Path

from meta_flow.context_pack import read_expansion
from meta_flow.state.current import validate_current_state_payload
from meta_flow.state.ledger_compaction import semantic_manifest


def test_semantic_manifest_never_falls_back_to_dispatch_or_run_identity() -> None:
    manifest = semantic_manifest(({"dispatch_id": "d", "run_id": "r", "event_type": "dispatch"},))
    assert manifest["rows"][0]["event_id"] is None
    assert manifest["rows"][0]["dispatch"] == {"dispatch_id": "d", "attempt_id": None}


def test_delivered_current_state_rejects_active_refs() -> None:
    state = {"schema_version": 2, "project_id": "x", "workflow_mode": "standard", "current_phase": "delivered", "blocked": False, "active_change": None, "active_story": "S", "active_context_ref": None, "active_delegation_ref": None, "pending_gate": None, "pending_checklist_path": None, "next_action": None, "open_risks": [], "authz_policy_refs": [], "routing_ref": None, "updated_at": "2026-01-01T00:00:00+00:00"}
    assert any(item.code == "delivered_active_reference" for item in validate_current_state_payload(state, mode="enforce"))


def test_new_read_expansion_has_explicit_authorization(tmp_path: Path) -> None:
    (tmp_path / "process/policies").mkdir(parents=True)
    (tmp_path / "process/policies/READ-POLICY.json").write_text(json.dumps({"full_doc_read_allowed_when":["human_audit"], "deny_default_reads":["process/stories/*-LLD.md"]}), encoding="utf-8")
    target = tmp_path / "process/stories/S-LLD.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    event = read_expansion.build_event(tmp_path, requested_path="process/stories/S-LLD.md", reason="human_audit", stage="CP6", agent="host", context_ref="process/context/x")
    assert event["outside_default_read_set"] is True
    assert event["expansion_authorized"] is True
    assert not read_expansion.validate_event(event, allowed_reasons={"human_audit"}, line_number=1)
