from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.checks import state_transition
from meta_flow.checks.frozen_cp6_evidence import (
    build_cp6_evidence_v2,
    build_cp6_revalidation_receipt,
)
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.state.checkpoint_projection import (
    CheckpointHeadV1,
    CheckpointProjectionV1,
)
from meta_flow.workflow import story_evidence


def cp5_projection(
    *,
    cr_id: str = "CR-062",
    result_ref: str = "process/checks/CP5-CR-062-V5.result.json",
    decision: str = "PASS",
) -> CheckpointProjectionV1:
    result = {
        "event_id": "CP5-CR-062-V5",
        "cr_id": cr_id,
        "checkpoint": "CP5",
        "decision": decision,
    }
    return CheckpointProjectionV1(
        target_cr_id=cr_id,
        target_checkpoint="CP5",
        heads=(
            CheckpointHeadV1(
                cr_id=cr_id,
                checkpoint="CP5",
                subject_id=cr_id,
                event_id="CP5-CR-062-V5",
                result_ref=result_ref,
                decision=decision,
                result=result,
                revision=1,
                selection_mode="legacy-single",
                provenance_event_ids=("CP5-CR-062-V5",),
            ),
        ),
        findings=(),
        selected_event_count=1,
        loaded_result_refs=(result_ref,),
        source_event_digest="a" * 64,
    )


def write_route_plan(root: Path) -> Path:
    path = root / "process" / "checks" / "CP0-CR158.route-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "decision": "PASS",
        "stages": [
            {"checkpoint": "CP0", "mode": "standard", "human_gate": "none"},
            {"checkpoint": "CP2", "mode": "standard", "human_gate": "required"},
            {"checkpoint": "CP3", "mode": "standard", "human_gate": "required"},
            {"checkpoint": "CP4", "mode": "standard", "human_gate": "none"},
            {"checkpoint": "CP5", "mode": "standard", "human_gate": "required"},
            {"checkpoint": "CP6", "mode": "standard", "human_gate": "none"},
            {"checkpoint": "CP7", "mode": "standard", "human_gate": "none"},
            {"checkpoint": "CP8", "mode": "standard", "human_gate": "required"},
        ],
        "checkpoint_applicability": {},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_state(root: Path, payload: dict) -> Path:
    path = root / "process" / "state" / "STATE.current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 2,
        "project_id": "demo",
        "workflow_mode": "standard",
        "current_phase": "story-planning",
        "blocked": False,
        "active_change": "CR-158",
        "pending_gate": None,
        "next_action": {"type": "continue", "text": "continue current phase"},
        "routing_ref": "process/.meta-flow-process.yaml",
        "updated_at": "2026-07-05T00:00:00+00:00",
    }
    state.update(payload)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_revalidation_event_observations(root: Path, identity: dict[str, str]) -> list[dict]:
    """写入五阶段真实事件 bytes，并返回 projector 消费的不可变 observations。"""

    kinds = ("authorization", "preregistration", "preflight", "projection", "completion")
    observations: list[dict] = []
    previous_digest = ""
    for index, kind in enumerate(kinds, start=1):
        payload = {
            "schema_version": 1, "kind": kind, **identity,
            "previous_digest": previous_digest, "sequence": index,
        }
        raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
        digest = hashlib.sha256(raw).hexdigest()
        path = root / f"{index:02d}-{kind}.json"
        path.write_bytes(raw)
        observations.append({
            "schema_version": 1,
            "evidence_ref": f"process/receipts/{path.name}",
            "bytes": path.read_bytes(), "bytes_digest": digest, "kind": kind,
            "previous_digest": previous_digest, "outer_identity": dict(identity),
        })
        previous_digest = digest
    return observations


class StateTransitionTests(unittest.TestCase):
    def test_a003_pgr3_f002_projector_requires_receipt_byte_observations(self) -> None:
        """PGR3-F002：正向投影必须来自 immutable receipt bytes/ref，而非手写摘要。"""
        identity = {
            "cr_id": "CR-X", "story_id": "STORY-X", "work_id": "W-X",
            "attempt_id": "attempt-random-42",
        }
        with tempfile.TemporaryDirectory() as directory:
            observations = write_revalidation_event_observations(Path(directory), identity)
            result = state_transition.project_cp6_revalidation_attempt(
                observations, expected_identity=identity,
                formal_story_status="ready-for-verification",
            )
            self.assertEqual(("READY", "COMPLETE", True), (result["decision"], result["phase"], result["complete"]))
            self.assertEqual("ready-for-verification", result["formal_story_status"])
            mutations = {
                "ref": {"evidence_ref": "process/../escape.json"},
                "bytes": {"bytes": b"tampered"},
                "digest": {"bytes_digest": "0" * 64},
                "kind": {"kind": "wrong"},
                "previous": {"previous_digest": "0" * 64},
                "identity": {"outer_identity": {**identity, "attempt_id": "other"}},
            }
            for name, mutation in mutations.items():
                changed = [dict(item) for item in observations]
                changed[2].update(mutation)
                with self.subTest(name=name):
                    blocked = state_transition.project_cp6_revalidation_attempt(
                        changed, expected_identity=identity,
                        formal_story_status="ready-for-verification",
                    )
                    self.assertEqual("BLOCKED", blocked["decision"])
            for field, value in (
                ("kind", "wrong"), ("previous_digest", "0" * 64),
                ("cr_id", "CR-OTHER"), ("story_id", "STORY-OTHER"),
                ("work_id", "W-OTHER"), ("attempt_id", "other"),
                ("schema_version", 99), ("extra", True),
            ):
                changed = [dict(item) for item in observations]
                inner = json.loads(changed[2]["bytes"])
                inner[field] = value
                raw = (json.dumps(inner, ensure_ascii=False, sort_keys=True) + "\n").encode()
                changed[2]["bytes"] = raw
                changed[2]["bytes_digest"] = hashlib.sha256(raw).hexdigest()
                blocked = state_transition.project_cp6_revalidation_attempt(changed, expected_identity=identity, formal_story_status="ready-for-verification")
                self.assertEqual("BLOCKED", blocked["decision"])
            for raw in (b"{invalid", json.dumps({"schema_version": 1}).encode()):
                changed = [dict(item) for item in observations]
                changed[2]["bytes"] = raw
                changed[2]["bytes_digest"] = hashlib.sha256(raw).hexdigest()
                self.assertEqual("BLOCKED", state_transition.project_cp6_revalidation_attempt(changed, expected_identity=identity, formal_story_status="ready-for-verification")["decision"])
            sequence = [dict(item) for item in observations]
            inner = json.loads(sequence[2]["bytes"])
            inner["sequence"] = 999
            raw = (json.dumps(inner, ensure_ascii=False, sort_keys=True) + "\n").encode()
            sequence[2]["bytes"] = raw
            sequence[2]["bytes_digest"] = hashlib.sha256(raw).hexdigest()
            self.assertEqual(
                "BLOCKED",
                state_transition.project_cp6_revalidation_attempt(
                    sequence, expected_identity=identity,
                    formal_story_status="ready-for-verification",
                )["decision"],
            )
            invalid_utf8 = [dict(item) for item in observations]
            invalid_utf8[2]["bytes"] = b"\xff"
            invalid_utf8[2]["bytes_digest"] = hashlib.sha256(b"\xff").hexdigest()
            self.assertEqual(
                "BLOCKED",
                state_transition.project_cp6_revalidation_attempt(
                    invalid_utf8, expected_identity=identity,
                    formal_story_status="ready-for-verification",
                )["decision"],
            )
            duplicate = [*observations, dict(observations[0])]
            self.assertEqual("BLOCKED", state_transition.project_cp6_revalidation_attempt(duplicate, expected_identity=identity, formal_story_status="ready-for-verification")["decision"])
            writes = []
            completion_target = Path(directory) / "completion.json"
            downstream_set = [{
                "producer": "P02",
                "receipt_digest": "a" * 64,
                "attempt_id": identity["attempt_id"],
            }]
            authorization = build_cp6_revalidation_receipt(
                kind="authorization",
                **identity,
                release_oid="b" * 40,
                process_oid="c" * 40,
                scope_digest="d" * 64,
                payload={
                    "previous_cp6_ref": "process/checks/previous.json",
                    "superseding_cp5_ref": "process/checks/cp5.json",
                    "approval_ref": "process/checkpoints/approval.json",
                    "work_authorization_ref": "process/works/W-X/WORK.yaml",
                    "plan_preimage_digest": "e" * 64,
                    "downstream_set_digest": canonical_digest(downstream_set),
                    "downstream_set": downstream_set,
                },
            ).as_dict()
            completion = story_evidence.run_cp6_revalidation_operation(
                request={
                    "action": "completion", "output": "json",
                    "authorization": authorization,
                    "target": completion_target, "event_observations": observations,
                    "expected_identity": identity,
                    "formal_story_status": "ready-for-verification",
                },
                services={
                    "resolve": lambda value: value,
                    "observe_current": lambda *_args, **_kwargs: {
                        "status": "CURRENT", "mutation_count": 0,
                        "observation": {"target_exists": completion_target.exists()},
                    },
                    "projector": state_transition.project_cp6_revalidation_attempt,
                    "create_once_writer": story_evidence._create_once_json,
                    "postcheck_reader": story_evidence._read_json,
                    "formal_truth_writer": lambda payload: writes.append(payload),
                },
            )
            self.assertEqual("COMPLETE", completion["phase"])
            self.assertEqual([], writes)

            tampered = [dict(item) for item in observations]
            inner = json.loads(tampered[2]["bytes"])
            inner["story_id"] = "STORY-OTHER"
            raw = (json.dumps(inner, ensure_ascii=False, sort_keys=True) + "\n").encode()
            tampered[2]["bytes"] = raw
            tampered[2]["bytes_digest"] = hashlib.sha256(raw).hexdigest()
            blocked_target = Path(directory) / "blocked-completion.json"
            blocked_calls = {"completion_writer": 0, "formal_writer": 0}

            def fail_completion_writer(*_args, **_kwargs):
                blocked_calls["completion_writer"] += 1
                self.fail("completion writer called after projector BLOCKED")

            def fail_formal_writer(*_args, **_kwargs):
                blocked_calls["formal_writer"] += 1
                self.fail("formal truth writer called after projector BLOCKED")

            blocked_completion = story_evidence.run_cp6_revalidation_operation(
                request={
                    "action": "completion", "output": "json",
                    "authorization": authorization,
                    "target": blocked_target, "event_observations": tampered,
                    "expected_identity": identity,
                    "formal_story_status": "ready-for-verification",
                },
                services={
                    "resolve": lambda value: value,
                    "observe_current": lambda *_args, **_kwargs: {
                        "status": "CURRENT", "mutation_count": 0,
                        "observation": {"target_exists": blocked_target.exists()},
                    },
                    "projector": state_transition.project_cp6_revalidation_attempt,
                    "create_once_writer": fail_completion_writer,
                    "postcheck_reader": lambda *_args, **_kwargs: self.fail(
                        "postcheck called after projector BLOCKED"
                    ),
                    "formal_truth_writer": fail_formal_writer,
                },
            )
            self.assertEqual(
                ("BLOCKED", 0, 2),
                (
                    blocked_completion["decision"],
                    blocked_completion["mutation_count"],
                    blocked_completion["exit_code"],
                ),
            )
            self.assertEqual({"completion_writer": 0, "formal_writer": 0}, blocked_calls)
            self.assertFalse(blocked_target.exists())
    # A3 mapping: TC02/03 initial admission, TC04/05 validated attempt chain,
    # COMP02 non-revalidation transition regression.
    def test_a3_tc04_tc05_bare_phase_mappings_cannot_complete_attempt(self) -> None:
        identity = {"cr_id": "CR-X", "story_id": "STORY-X", "work_id": "W-X", "attempt_id": "a1"}
        result = state_transition.project_cp6_revalidation_attempt(
            [
                {"attempt_id": "a1", "phase": phase}
                for phase in state_transition.CP6_REVALIDATION_PHASES
            ],
            expected_identity=identity,
            formal_story_status="ready-for-verification",
        )
        self.assertEqual("BLOCKED", result["decision"])

    def test_p02_attempt_projector_is_monotonic_and_preserves_formal_status(self) -> None:
        identity = {"cr_id": "CR-X", "story_id": "STORY-X", "work_id": "W-X", "attempt_id": "a1"}
        with tempfile.TemporaryDirectory() as directory:
            events = write_revalidation_event_observations(Path(directory), identity)
            for count, phase in enumerate(state_transition.CP6_REVALIDATION_PHASES, start=1):
                result = state_transition.project_cp6_revalidation_attempt(
                    events[:count], expected_identity=identity,
                    formal_story_status="ready-for-verification",
                )
                self.assertEqual(("READY", phase), (result["decision"], result["phase"]))
                self.assertEqual(count == len(events), result["complete"])
                self.assertEqual("ready-for-verification", result["formal_story_status"])

    def test_p02_attempt_projector_fails_closed_for_skip_duplicate_and_cross_attempt(self) -> None:
        identity = {"cr_id": "CR-X", "story_id": "STORY-X", "work_id": "W-X", "attempt_id": "a1"}
        with tempfile.TemporaryDirectory() as directory:
            events = write_revalidation_event_observations(Path(directory), identity)
            cases = {
                "skip": events[1:2],
                "duplicate": [events[0], events[0]],
                "cross-attempt": [{**events[0], "outer_identity": {**identity, "attempt_id": "other"}}],
                "bad-kind": [{**events[0], "kind": "wrong"}],
                "bad-digest": [{**events[0], "bytes_digest": "A" * 64}],
            }
            for name, candidate in cases.items():
                with self.subTest(name=name):
                    result = state_transition.project_cp6_revalidation_attempt(
                        candidate, expected_identity=identity,
                        formal_story_status="ready-for-verification",
                    )
                    self.assertEqual("BLOCKED", result["decision"])

    def _c0_result(
        self,
        *,
        failed_consumer: bool = False,
        stale_semantic_contract: bool = False,
    ) -> state_transition.C0ResultV1:
        project_root = Path(__file__).parents[1]
        frozen = [
            build_cp6_evidence_v2(
                project_root,
                story_id=f"STORY-CR061-S0{index}",
                release_oid="a" * 40,
                process_oid="b" * 40,
                scope_digest="c" * 64,
                implementation_digest=chr(99 + index) * 64,
                dependency_digests={"upstream": str(index) * 64},
                cp6_result_ref=f"process/checks/CP6-STORY-CR061-S0{index}.result.json",
            ).as_dict()
            for index in range(1, 4)
        ]
        if stale_semantic_contract:
            frozen[0] = {**frozen[0], "contract_digest": "0" * 64}
        consumers = [
            state_transition.project_c0_consumer(
                consumer_id=f"C0-CONSUMER-{index:02d}",
                operation=f"operation-{index:02d}",
                attempts=[
                    {
                        "returncode": 1 if failed_consumer and index == 1 else 0,
                        "stdout": "PASS",
                        "stderr": "",
                    }
                ],
                absolute_process_path="/bound/process",
            )
            for index in range(1, 12)
        ]
        return state_transition.build_c0_result(
            project_root=project_root,
            cr_id="CR-061",
            release_oid="a" * 40,
            process_oid="b" * 40,
            scope_digest="c" * 64,
            input_evidence_refs=[
                f"process/{kind}/STORY-CR061-S0{index}.json"
                for index in range(1, 4)
                for kind in ("checks", "returns", "evidence")
            ],
            frozen_evidence=frozen,
            consumer_inventory=consumers,
            planned_transitions=[
                {
                    "subject": "STORY-CR061-S01",
                    "from": "bootstrap-cp6-pass",
                    "to": "ready-for-verification",
                }
            ],
            mutation_allowlist=["process/DEVELOPMENT-PLAN.yaml"],
        )

    def test_c0_result_v1_has_exact_21_keys_and_native_digest(self) -> None:
        result = self._c0_result()
        payload = result.as_dict()

        self.assertEqual(21, len(payload))
        self.assertEqual(state_transition.C0_RESULT_FIELDS, set(payload))
        self.assertEqual("READY", payload["decision"])
        self.assertEqual(3, len(payload["replay_results"]))
        self.assertEqual(11, len(payload["consumer_inventory"]))
        self.assertEqual(0, payload["bootstrap_consumer_count"])
        self.assertEqual(0, payload["legacy_projector_consumer_count"])
        self.assertEqual(payload, state_transition.C0ResultV1.from_dict(payload).as_dict())

    def test_c0_blocks_stale_semantic_contract_before_ready(self) -> None:
        payload = self._c0_result(stale_semantic_contract=True).as_dict()

        self.assertEqual("BLOCKED", payload["decision"])
        self.assertIn("C0_REPLAY_BLOCKED:STORY-CR061-S01", payload["blockers"])
        self.assertIn("C0_REPLAY_MUST_PASS_3_OF_3", payload["blockers"])
        self.assertEqual(
            "revalidation-required",
            payload["replay_results"][0]["admission_decision"],
        )

    def test_c0_result_v1_rejects_unknown_field(self) -> None:
        payload = self._c0_result().as_dict()
        payload["unknown"] = True

        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            state_transition.C0ResultV1.from_dict(payload)

    def test_c0_result_blocks_failed_public_consumer(self) -> None:
        payload = self._c0_result(failed_consumer=True).as_dict()

        self.assertEqual("BLOCKED", payload["decision"])
        self.assertIn("C0_CONSUMER_REPLAY_BLOCKED", payload["blockers"])

    def test_c0_development_plan_projector_has_one_deterministic_state_mapping(self) -> None:
        payload = {
            "waves": [
                {
                    "stories": [
                        {
                            "story_id": f"STORY-CR061-S0{index}",
                            "status": "lld-ready",
                            "lld_gate": {"status": "ready-for-review"},
                            "dev_gate": {
                                "lld_confirmed": False,
                                "cp5_confirmed": False,
                                "dependencies_satisfied": False,
                                "file_conflict_free": False,
                                "implementation_authorized": False,
                            },
                        }
                        for index in range(1, 6)
                    ]
                }
            ]
        }

        projected, transitions = state_transition.project_c0_development_plan(
            payload,
            cr_id="CR-061",
        )
        stories = {
            story["story_id"]: story
            for story in projected["waves"][0]["stories"]
        }

        self.assertEqual("ready-for-verification", stories["STORY-CR061-S01"]["status"])
        self.assertEqual("ready-for-verification", stories["STORY-CR061-S03"]["status"])
        self.assertEqual("dev-ready", stories["STORY-CR061-S04"]["status"])
        self.assertTrue(stories["STORY-CR061-S04"]["dev_gate"]["dependencies_satisfied"])
        self.assertTrue(stories["STORY-CR061-S04"]["dev_gate"]["implementation_authorized"])
        self.assertEqual("lld-approved", stories["STORY-CR061-S05"]["status"])
        self.assertFalse(stories["STORY-CR061-S05"]["dev_gate"]["dependencies_satisfied"])
        self.assertFalse(stories["STORY-CR061-S05"]["dev_gate"]["implementation_authorized"])
        self.assertEqual(5, len(transitions))
        self.assertEqual(payload, {
            "waves": [
                {
                    "stories": [
                        {
                            "story_id": f"STORY-CR061-S0{index}",
                            "status": "lld-ready",
                            "lld_gate": {"status": "ready-for-review"},
                            "dev_gate": {
                                "lld_confirmed": False,
                                "cp5_confirmed": False,
                                "dependencies_satisfied": False,
                                "file_conflict_free": False,
                                "implementation_authorized": False,
                            },
                        }
                        for index in range(1, 6)
                    ]
                }
            ]
        })

        replayed, _replayed_transitions = state_transition.project_c0_development_plan(
            projected,
            cr_id="CR-061",
        )
        self.assertEqual(projected, replayed)

    def test_c0_development_plan_projector_rejects_missing_story(self) -> None:
        payload = {
            "waves": [
                {
                    "stories": [
                        {
                            "story_id": f"STORY-CR061-S0{index}",
                            "status": "lld-ready",
                            "lld_gate": {},
                            "dev_gate": {},
                        }
                        for index in range(1, 5)
                    ]
                }
            ]
        }

        with self.assertRaisesRegex(ValueError, "C0 stories missing"):
            state_transition.project_c0_development_plan(payload, cr_id="CR-061")

    def test_c0_development_plan_projector_repairs_prior_regression_monotonically(
        self,
    ) -> None:
        payload = {
            "waves": [
                {
                    "stories": [
                        {
                            "story_id": f"STORY-CR061-S0{index}",
                            "status": (
                                "dev-ready"
                                if index == 4
                                else "lld-approved"
                                if index == 5
                                else "ready-for-verification"
                            ),
                            "lld_gate": {"status": "approved"},
                            "dev_gate": {
                                "lld_confirmed": True,
                                "cp5_confirmed": True,
                                "dependencies_satisfied": index != 5,
                                "file_conflict_free": True,
                                "implementation_authorized": index != 5,
                            },
                        }
                        for index in range(1, 6)
                    ]
                }
            ]
        }
        prior_transitions = [
            {
                "subject": "STORY-CR061-S04",
                "from": "ready-for-verification",
                "to": "dev-ready",
            },
            {
                "subject": "STORY-CR061-S05",
                "from": "ready-for-verification",
                "to": "lld-approved",
            },
        ]

        projected, transitions = state_transition.project_c0_development_plan(
            payload,
            cr_id="CR-061",
            prior_transitions=prior_transitions,
        )
        stories = {
            story["story_id"]: story
            for story in projected["waves"][0]["stories"]
        }

        self.assertEqual("ready-for-verification", stories["STORY-CR061-S04"]["status"])
        self.assertEqual("ready-for-verification", stories["STORY-CR061-S05"]["status"])
        self.assertTrue(stories["STORY-CR061-S04"]["dev_gate"]["dependencies_satisfied"])
        self.assertTrue(stories["STORY-CR061-S05"]["dev_gate"]["dependencies_satisfied"])
        self.assertTrue(stories["STORY-CR061-S04"]["dev_gate"]["implementation_authorized"])
        self.assertTrue(stories["STORY-CR061-S05"]["dev_gate"]["implementation_authorized"])
        self.assertEqual(
            {
                "STORY-CR061-S04",
                "STORY-CR061-S05",
            },
            {transition["subject"] for transition in transitions},
        )
        self.assertTrue(
            all(
                transition["reason"] == "C0_REPAIR_REGRESSIVE_PRIOR_PROJECTION"
                for transition in transitions
            )
        )

    def test_cp5_passage_projects_only_dependency_roots_to_dev_ready(self) -> None:
        payload = {
            "waves": [
                {
                    "stories": [
                        {
                            "story_id": "STORY-CR062-S01",
                            "cr_id": "CR-062",
                            "status": "lld-ready",
                            "depends_on": [],
                            "lld_gate": {"status": "ready"},
                            "dev_gate": {
                                "cp5_confirmed": False,
                                "dependencies_satisfied": True,
                                "file_conflict_free": True,
                                "implementation_authorized": False,
                                "lld_confirmed": False,
                            },
                        },
                        {
                            "story_id": "STORY-CR062-S02",
                            "cr_id": "CR-062",
                            "status": "lld-ready",
                            "depends_on": ["STORY-CR062-S01"],
                            "lld_gate": {"status": "ready"},
                            "dev_gate": {
                                "cp5_confirmed": False,
                                "dependencies_satisfied": False,
                                "file_conflict_free": True,
                                "implementation_authorized": False,
                                "lld_confirmed": False,
                            },
                        },
                    ]
                }
            ]
        }
        result_ref = "process/checks/CP5-CR-062-V5.result.json"
        projection = cp5_projection(result_ref=result_ref)
        approval = {
            "event_id": "GATE-CR062-CP5-V5",
            "event_type": "human_gate_approval",
            "cr_id": "CR-062",
            "work_id": "GOV-006-CONTROL-001",
            "result_ref": result_ref,
            "decision": "approve",
            "status": "approved",
            "gate": "CP5_ALL_STORIES_LLD",
            "approval_kind_version": 1,
            "approval_kind": "checkpoint_passage",
            "checkpoint": "CP5",
        }

        projected, transitions = state_transition.project_cp5_development_plan(
            payload,
            cr_id="CR-062",
            projection=projection,
            gate_events=[approval],
        )

        stories = {
            story["story_id"]: story for story in projected["waves"][0]["stories"]
        }
        self.assertEqual("dev-ready", stories["STORY-CR062-S01"]["status"])
        self.assertEqual("lld-approved", stories["STORY-CR062-S02"]["status"])
        self.assertTrue(
            stories["STORY-CR062-S01"]["dev_gate"]["implementation_authorized"]
        )
        self.assertFalse(
            stories["STORY-CR062-S02"]["dev_gate"]["implementation_authorized"]
        )
        self.assertEqual(2, len(transitions))
        self.assertEqual("lld-ready", payload["waves"][0]["stories"][0]["status"])

        replayed, replay_transitions = state_transition.project_cp5_development_plan(
            projected,
            cr_id="CR-062",
            projection=projection,
            gate_events=[approval],
        )
        self.assertEqual(projected, replayed)
        self.assertEqual((), replay_transitions)

    def test_cp5_projection_rejects_non_passage_or_duplicate_approval(self) -> None:
        payload = {
            "waves": [
                {
                    "stories": [
                        {
                            "story_id": "STORY-CR062-S01",
                            "cr_id": "CR-062",
                            "status": "lld-ready",
                            "depends_on": [],
                            "lld_gate": {"status": "ready"},
                            "dev_gate": {},
                        }
                    ]
                }
            ]
        }
        result_ref = "process/checks/CP5-CR-062-V5.result.json"
        projection = cp5_projection(result_ref=result_ref)
        passage = {
            "event_id": "GATE-CR062-CP5-V5",
            "event_type": "human_gate_approval",
            "cr_id": "CR-062",
            "work_id": "GOV-006-CONTROL-001",
            "result_ref": result_ref,
            "decision": "approve",
            "status": "approved",
            "gate": "CP5_ALL_STORIES_LLD",
            "approval_kind_version": 1,
            "approval_kind": "checkpoint_passage",
            "checkpoint": "CP5",
        }
        scope_amendment = {
            **passage,
            "event_id": "GATE-CR062-SCOPE-V1",
            "approval_kind": "scope_amendment",
            "scope_version": 5,
            "scope_digest": "b" * 64,
            "authorized_actions": ["add-one-leaf"],
            "decision_ref": "process/checkpoints/CP3-CR-062.md",
        }
        for gate_events in ([scope_amendment], [passage, dict(passage)]):
            with self.subTest(event_count=len(gate_events)), self.assertRaisesRegex(
                ValueError,
                "exactly one approval bound to canonical head",
            ):
                state_transition.project_cp5_development_plan(
                    payload,
                    cr_id="CR-062",
                    projection=projection,
                    gate_events=gate_events,
                )

    def test_cp6_pass_projects_story_and_only_satisfied_downstream_to_dev_ready(
        self,
    ) -> None:
        payload = {
            "waves": [
                {
                    "stories": [
                        {
                            "story_id": "STORY-CR061-S04",
                            "status": "dev-ready",
                            "depends_on": [],
                            "dev_gate": {
                                "cp5_confirmed": True,
                                "dependencies_satisfied": True,
                                "file_conflict_free": True,
                                "implementation_authorized": True,
                                "lld_confirmed": True,
                            },
                        },
                        {
                            "story_id": "STORY-CR061-S05",
                            "status": "lld-approved",
                            "depends_on": ["STORY-CR061-S04"],
                            "dev_gate": {
                                "cp5_confirmed": True,
                                "dependencies_satisfied": False,
                                "file_conflict_free": True,
                                "implementation_authorized": False,
                                "lld_confirmed": True,
                            },
                        },
                    ]
                }
            ]
        }

        projected, transitions = state_transition.project_cp6_development_plan(
            payload,
            result={
                "checkpoint": "CP6",
                "decision": "PASS",
                "story_id": "STORY-CR061-S04",
            },
        )

        stories = {
            story["story_id"]: story for story in projected["waves"][0]["stories"]
        }
        self.assertEqual(
            "ready-for-verification",
            stories["STORY-CR061-S04"]["status"],
        )
        self.assertEqual("dev-ready", stories["STORY-CR061-S05"]["status"])
        self.assertTrue(
            stories["STORY-CR061-S05"]["dev_gate"]["dependencies_satisfied"]
        )
        self.assertTrue(
            stories["STORY-CR061-S05"]["dev_gate"]["implementation_authorized"]
        )
        self.assertEqual(2, len(transitions))

    def test_cp6_projection_rejects_closed_gate(self) -> None:
        payload = {
            "waves": [
                {
                    "stories": [
                        {
                            "story_id": "STORY-CR061-S04",
                            "status": "dev-ready",
                            "dev_gate": {
                                "cp5_confirmed": True,
                                "dependencies_satisfied": False,
                                "file_conflict_free": True,
                                "implementation_authorized": True,
                                "lld_confirmed": True,
                            },
                        }
                    ]
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "fully open dev_gate"):
            state_transition.project_cp6_development_plan(
                payload,
                result={
                    "checkpoint": "CP6",
                    "decision": "PASS",
                    "story_id": "STORY-CR061-S04",
                },
            )

    def test_cp5_transition_accepts_missing_state_projection_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            output = StringIO()
            with redirect_stdout(output):
                exit_code = state_transition.main(
                    ["--project-root", str(root), "--route-plan", str(route), "--approved-gate", "CP5", "--output", "json"]
                )
            self.assertEqual(0, exit_code)
            self.assertEqual("OK", json.loads(output.getvalue())["status"])
            self.assertFalse((root / "process" / "state" / "STATE.current.json").exists())

    def test_cp5_transition_rejects_missing_route_instead_of_treating_it_as_missing_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing_route = root / "process" / "checks" / "missing-route.json"
            output = StringIO()
            with redirect_stdout(output):
                exit_code = state_transition.main(
                    [
                        "--project-root",
                        str(root),
                        "--route-plan",
                        str(missing_route),
                        "--approved-gate",
                        "CP5",
                        "--output",
                        "json",
                    ]
                )

            self.assertEqual(1, exit_code)
            self.assertEqual("FAIL", json.loads(output.getvalue())["status"])

    def test_chronology_accepts_complete_timezone_aware_order(self) -> None:
        nodes = [
            state_transition.ChronologyNode("producer-complete", "2026-07-12T00:00:00Z", "producer"),
            state_transition.ChronologyNode("checkpoint-created", "2026-07-12T00:01:00Z", "checkpoint"),
            state_transition.ChronologyNode("gate-opened", "2026-07-12T00:02:00Z", "gate"),
            state_transition.ChronologyNode("reviewed", "2026-07-12T00:03:00Z", "review"),
            state_transition.ChronologyNode("approved", "2026-07-12T00:04:00Z", "approval"),
            state_transition.ChronologyNode("downstream-dispatch", "2026-07-12T00:05:00Z", "dispatch"),
        ]
        self.assertEqual([], state_transition.validate_chronology(nodes))

    def test_chronology_rejects_each_core_order_violation(self) -> None:
        nodes = [
            state_transition.ChronologyNode("producer-complete", "2026-07-12T00:02:00Z", "producer"),
            state_transition.ChronologyNode("checkpoint-created", "2026-07-12T00:01:00Z", "checkpoint"),
        ]
        findings = state_transition.validate_chronology(nodes)
        self.assertEqual(["TEMPORAL_ORDER_VIOLATION"], [finding.code for finding in findings])

    def test_conditional_approval_requires_conditions_satisfied(self) -> None:
        nodes = [
            state_transition.ChronologyNode("gate-opened", "2026-07-12T00:00:00Z", "gate"),
            state_transition.ChronologyNode("conditional-received", "2026-07-12T00:01:00Z", "conditional"),
            state_transition.ChronologyNode("approved", "2026-07-12T00:02:00Z", "approval"),
        ]
        decision, findings = state_transition.derive_gate_decision(nodes)
        self.assertEqual("pending", decision)
        self.assertIn("CONDITIONS_UNSATISFIED", [finding.code for finding in findings])

    def test_conditional_approval_with_conditions_and_dispatch_is_approved(self) -> None:
        nodes = [
            state_transition.ChronologyNode("gate-opened", "2026-07-12T00:00:00Z", "gate"),
            state_transition.ChronologyNode("conditional-received", "2026-07-12T00:01:00Z", "conditional"),
            state_transition.ChronologyNode("conditions-satisfied", "2026-07-12T00:02:00Z", "conditions"),
            state_transition.ChronologyNode("approved", "2026-07-12T00:03:00Z", "approval"),
            state_transition.ChronologyNode("downstream-dispatch", "2026-07-12T00:04:00Z", "dispatch"),
        ]
        decision, findings = state_transition.derive_gate_decision(nodes)
        self.assertEqual("approved", decision)
        self.assertEqual([], findings)
        self.assertEqual([], state_transition.validate_phase_gate_state({"pending_gate": None}, nodes))

    def test_phase_work_without_gate_is_not_a_future_gate_fact(self) -> None:
        findings = state_transition.validate_phase_gate_state(
            {"current_phase": "solution-design", "pending_gate": None},
            [],
        )
        self.assertEqual([], findings)

    def test_review_without_opened_gate_is_rejected(self) -> None:
        findings = state_transition.validate_phase_gate_state(
            {"current_phase": "story-execution", "pending_gate": None},
            [state_transition.ChronologyNode("reviewed", "2026-07-12T00:00:00Z", "review")],
        )
        self.assertIn("PHASE_GATE_CONFLATION", [finding.code for finding in findings])

    def test_approved_gate_without_downstream_transition_is_rejected(self) -> None:
        findings = state_transition.validate_phase_gate_state(
            {"current_phase": "story-execution", "pending_gate": None},
            [
                state_transition.ChronologyNode("gate-opened", "2026-07-12T00:00:00Z", "gate"),
                state_transition.ChronologyNode("reviewed", "2026-07-12T00:01:00Z", "review"),
                state_transition.ChronologyNode("approved", "2026-07-12T00:02:00Z", "approval"),
            ],
        )
        self.assertIn("PHASE_GATE_CONFLATION", [finding.code for finding in findings])

    def test_timezone_is_required_for_chronology(self) -> None:
        findings = state_transition.validate_chronology(
            [state_transition.ChronologyNode("gate-opened", "2026-07-12T00:00:00", "gate")]
        )
        self.assertEqual(["UNPARSEABLE_TIMESTAMP"], [finding.code for finding in findings])
    def test_cp4_pass_requires_auto_advance_to_cp5_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(root, {"next_action": {"type": "continue", "text": "等待用户继续推进 CP5"}})

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                checkpoint="CP4",
                decision="PASS",
            )

            self.assertEqual([], warnings)
            self.assertTrue(any("pending_gate=CP5" in error for error in errors))

    def test_cp4_pass_accepts_state_stopped_at_cp5_required_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "pending_gate": "CP5",
                    "pending_checklist_path": "process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md",
                    "next_action": {"type": "await_user", "text": "review CP5"},
                },
            )

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                checkpoint="CP4",
                decision="PASS",
            )

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_approved_cp3_accepts_real_cp4_automatic_work_before_cp5_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "current_phase": "lld-design",
                    "next_action": {"type": "continue", "text": "complete CP4 design evidence"},
                },
            )

            errors, _warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                approved_gate="CP3",
            )

            self.assertEqual([], errors)

    def test_cp4_pass_opens_real_cp5_pending_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "pending_gate": "CP5",
                    "pending_checklist_path": "process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md",
                    "next_action": {"type": "await_user", "text": "review CP5"},
                },
            )
            errors, warnings = state_transition.validate_transition(
                route_plan_path=route, state_path=state, checkpoint="CP4", decision="PASS"
            )
            self.assertEqual(([], []), (errors, warnings))

    def test_approved_cp5_accepts_auto_advance_to_cp8_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "current_phase": "documentation",
                    "pending_gate": "CP8",
                    "pending_checklist_path": "process/checkpoints/CP8-DELIVERY-READINESS.md",
                    "next_action": {"type": "await_user", "text": "review CP8"},
                },
            )

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                approved_gate="CP5",
            )

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_approved_cp5_accepts_story_execution_before_cp8_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "current_phase": "story-execution",
                    "active_change": "CR-158",
                    "pending_gate": None,
                    "next_action": {"type": "inline_implementation", "text": "implement CP6 work"},
                },
            )

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                approved_gate="CP5",
            )

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_approved_cp5_accepts_formal_active_phase_during_automatic_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "current_phase": "P5-release-governance-convergence",
                    "active_change": "CR-072",
                    "pending_gate": None,
                    "next_action": {
                        "type": "continue_active_change",
                        "text": "Continue active formal change CR-072.",
                        "stop_reason": None,
                    },
                    "formal_truth_projection": {
                        "active_phase_ids": ["P5-release-governance-convergence"],
                        "active_cr_ids": ["CR-072"],
                    },
                },
            )

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                approved_gate="CP5",
            )

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_approved_cp8_accepts_true_delivered_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "current_phase": "delivered",
                    "active_change": None,
                    "pending_gate": None,
                    "next_action": {"type": "done", "text": "workflow delivered", "stop_reason": "delivered"},
                },
            )

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                approved_gate="CP8",
            )

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_approved_cp8_rejects_incomplete_or_false_delivered_state(self) -> None:
        invalid_states = (
            {
                "current_phase": "delivered",
                "active_change": None,
                "pending_gate": None,
                "next_action": {"type": "done", "stop_reason": "no_remaining_route"},
            },
            {
                "current_phase": "delivered",
                "active_change": None,
                "pending_gate": "CP7",
                "next_action": {"type": "done", "stop_reason": "delivered"},
            },
            {
                "current_phase": "delivered",
                "active_change": "CR-158",
                "pending_gate": None,
                "next_action": {"type": "done", "stop_reason": "delivered"},
            },
            {
                "current_phase": "documentation",
                "active_change": None,
                "pending_gate": None,
                "next_action": {"type": "done", "stop_reason": "delivered"},
            },
        )
        for state_patch in invalid_states:
            with self.subTest(state_patch=state_patch), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(root, state_patch)

                errors, _warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    approved_gate="CP8",
                )

                self.assertTrue(any("true delivered terminal state" in error for error in errors))

    def test_approved_cp8_accepts_legitimate_interrupt_without_pending_gate(self) -> None:
        for stop_reason in ("authorization_required", "workflow_health_threshold"):
            with self.subTest(stop_reason=stop_reason), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(
                    root,
                    {
                        "current_phase": "documentation",
                        "active_change": "CR-158",
                        "pending_gate": None,
                        "next_action": {"type": "blocked", "text": "legitimate interruption", "stop_reason": stop_reason},
                    },
                )

                errors, warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    approved_gate="CP8",
                )

                self.assertEqual([], errors)
                self.assertEqual([], warnings)

    def test_explicit_stop_reason_allows_blocked_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "next_action": {
                        "type": "blocked",
                        "text": "authorization required before continuing",
                        "stop_reason": "authorization_required",
                    }
                },
            )

            errors, _warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                approved_gate="CP3",
            )

            self.assertEqual([], errors)

    def test_cp7_pass_like_decisions_reject_stale_failure_stop_reasons(self) -> None:
        for decision in ("PASS", "PASS_WITH_RISK"):
            for stop_reason in ("needs_rework", "needs_design_clarification", "blocked"):
                with self.subTest(decision=decision, stop_reason=stop_reason), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    route = write_route_plan(root)
                    state = write_state(
                        root,
                        {
                            "next_action": {
                                "type": "blocked",
                                "text": "stale failure state",
                                "stop_reason": stop_reason,
                            }
                        },
                    )

                    errors, _warnings = state_transition.validate_transition(
                        route_plan_path=route,
                        state_path=state,
                        checkpoint="CP7",
                        decision=decision,
                    )

                    self.assertTrue(any("cannot retain failure stop_reason" in error for error in errors))
                    self.assertTrue(any("pending_gate=CP8" in error for error in errors))

    def test_cp7_pass_like_decisions_accept_pending_cp8(self) -> None:
        for decision in ("PASS", "PASS_WITH_RISK"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(
                    root,
                    {
                        "current_phase": "documentation",
                        "pending_gate": "CP8",
                        "pending_checklist_path": "process/checkpoints/CP8-DELIVERY-READINESS.md",
                        "next_action": {"type": "await_user", "text": "review CP8"},
                    },
                )

                errors, warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    checkpoint="CP7",
                    decision=decision,
                )

                self.assertEqual([], errors)
                self.assertEqual([], warnings)

    def test_cp7_pass_like_decision_accepts_next_story_before_final_cp8(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "current_phase": "story-execution",
                    "active_change": "CR-158",
                    "active_story": "STORY-NEXT",
                    "pending_gate": None,
                    "next_action": {"type": "inline_implementation", "text": "advance dependency graph"},
                },
            )

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                checkpoint="CP7",
                decision="PASS_WITH_RISK",
            )

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_cp7_pass_accepts_decision_compatible_interrupts(self) -> None:
        for stop_reason in ("authorization_required", "workflow_health_threshold"):
            with self.subTest(stop_reason=stop_reason), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(
                    root,
                    {
                        "next_action": {
                            "type": "blocked",
                            "text": "legitimate workflow interruption",
                            "stop_reason": stop_reason,
                        }
                    },
                )

                errors, _warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    checkpoint="CP7",
                    decision="PASS",
                )

                self.assertEqual([], errors)

    def test_historical_pass_like_result_accepts_true_delivered_terminal_replay(self) -> None:
        for checkpoint in ("CP4", "CP7"):
            for decision in ("PASS", "PASS_WITH_RISK"):
                with self.subTest(checkpoint=checkpoint, decision=decision), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    route = write_route_plan(root)
                    state = write_state(
                        root,
                        {
                            "current_phase": "delivered",
                            "active_change": None,
                            "pending_gate": None,
                            "next_action": {"type": "done", "text": "workflow delivered", "stop_reason": "delivered"},
                        },
                    )

                    errors, warnings = state_transition.validate_transition(
                        route_plan_path=route,
                        state_path=state,
                        checkpoint=checkpoint,
                        decision=decision,
                    )

                    self.assertEqual([], errors)
                    self.assertEqual([], warnings)

    def test_pass_like_terminal_replay_requires_complete_delivered_state(self) -> None:
        invalid_states = (
            {"current_phase": "delivered", "active_change": "CR-158", "next_action": {"stop_reason": "delivered"}},
            {"current_phase": "delivered", "active_change": None, "pending_gate": "CP8", "next_action": {"stop_reason": "delivered"}},
            {"current_phase": "delivered", "active_change": None, "next_action": {"stop_reason": "no_remaining_route"}},
            {"current_phase": "documentation", "active_change": None, "next_action": {"stop_reason": "delivered"}},
        )
        for state_patch in invalid_states:
            with self.subTest(state_patch=state_patch), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(root, state_patch)

                errors, _warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    checkpoint="CP7",
                    decision="PASS",
                )

                self.assertTrue(errors)

    def test_failure_result_replay_rejects_delivered_stop_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "current_phase": "delivered",
                    "active_change": None,
                    "pending_gate": None,
                    "next_action": {"type": "done", "text": "workflow delivered", "stop_reason": "delivered"},
                },
            )

            errors, _warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                checkpoint="CP7",
                decision="NEEDS_REWORK",
            )

            self.assertTrue(any("stop_reason in {needs_rework}" in error for error in errors))

    def test_failure_decisions_accept_decision_compatible_stop_reasons(self) -> None:
        cases = (
            ("FAIL", "blocked"),
            ("BLOCKED", "blocked"),
            ("BLOCKED", "authorization_required"),
            ("BLOCKED", "workflow_health_threshold"),
            ("NEEDS_REWORK", "needs_rework"),
            ("NEEDS_DESIGN_CLARIFICATION", "needs_design_clarification"),
        )
        for decision, stop_reason in cases:
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(
                    root,
                    {"next_action": {"type": "blocked", "text": "failure", "stop_reason": stop_reason}},
                )

                errors, _warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    checkpoint="CP7",
                    decision=decision,
                )

                self.assertEqual([], errors)

    def test_failure_decisions_reject_incompatible_stop_reasons(self) -> None:
        cases = (
            ("FAIL", "authorization_required"),
            ("FAIL", "workflow_health_threshold"),
            ("BLOCKED", "needs_rework"),
            ("BLOCKED", "needs_design_clarification"),
            ("NEEDS_REWORK", "blocked"),
            ("NEEDS_REWORK", "authorization_required"),
            ("NEEDS_REWORK", "workflow_health_threshold"),
            ("NEEDS_REWORK", "needs_design_clarification"),
            ("NEEDS_DESIGN_CLARIFICATION", "blocked"),
            ("NEEDS_DESIGN_CLARIFICATION", "authorization_required"),
            ("NEEDS_DESIGN_CLARIFICATION", "workflow_health_threshold"),
            ("NEEDS_DESIGN_CLARIFICATION", "needs_rework"),
        )
        for decision, stop_reason in cases:
            with self.subTest(decision=decision, stop_reason=stop_reason), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(
                    root,
                    {"next_action": {"type": "blocked", "text": "wrong failure", "stop_reason": stop_reason}},
                )

                errors, _warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    checkpoint="CP7",
                    decision=decision,
                )

                self.assertTrue(any("must leave matching stop_reason" in error for error in errors))

    def test_unknown_verification_decision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {"next_action": {"type": "continue", "text": "unknown result"}},
            )

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                checkpoint="CP7",
                decision="CHECK_HARNESS_ERROR",
            )

            self.assertEqual([], warnings)
            self.assertTrue(
                any("not registered in the verification outcome family" in error for error in errors)
            )

    def test_cli_reports_state_transition_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            write_state(root, {"next_action": {"type": "continue", "text": "manual continue requested"}})
            output = StringIO()

            with redirect_stdout(output):
                exit_code = state_transition.main(
                    [
                        "--project-root",
                        str(root),
                        "--route-plan",
                        str(route),
                        "--checkpoint",
                        "CP4",
                        "--decision",
                        "PASS",
                    ]
                )

            self.assertEqual(1, exit_code)
            self.assertIn("State Transition Check: FAIL", output.getvalue())
            self.assertIn("pending_gate=CP5", output.getvalue())

    def test_cli_reports_chronology_findings_as_stable_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload_path = root / "chronology.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "events": [
                            {"kind": "gate-opened", "occurred_at": "2026-07-12T00:01:00Z", "source_ref": "gate"},
                            {"kind": "approved", "occurred_at": "2026-07-12T00:00:00Z", "source_ref": "approval"},
                        ],
                        "state": {"pending_gate": None},
                    }
                ),
                encoding="utf-8",
            )
            output = StringIO()

            with redirect_stdout(output):
                exit_code = state_transition.main(
                    ["--chronology-events", str(payload_path), "--output", "json"]
                )

            result = json.loads(output.getvalue())
            self.assertEqual(1, exit_code)
            self.assertEqual("FAIL", result["status"])
            self.assertEqual("pending", result["decision"])
            self.assertEqual("TEMPORAL_ORDER_VIOLATION", result["findings"][0]["code"])


if __name__ == "__main__":
    unittest.main()
