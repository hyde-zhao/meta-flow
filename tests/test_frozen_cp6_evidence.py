from __future__ import annotations

import json
import unittest

from meta_flow.checks import frozen_cp6_evidence
from meta_flow.checks.frozen_cp6_evidence import (
    Cp6RevalidationAuthorizationV1,
    Cp6RevalidationReceiptV1,
    FrozenCp6EvidenceError,
    build_cp6_revalidation_receipt,
    compare_frozen_evidence,
    freeze_cp6_evidence,
    freeze_cp6_revalidation_receipt,
    project_story_admission,
    project_story_admissions,
)
from meta_flow.project.onboarding_contract import canonical_digest


def evidence(*, dependency_digest: str = "a" * 64) -> dict[str, object]:
    return {
        "schema_version": 1,
        "story_id": "STORY-CR061-S02",
        "release_oid": "1" * 40,
        "process_oid": "2" * 40,
        "scope_digest": "3" * 64,
        "implementation_digest": "4" * 64,
        "dependency_digests": {"STORY-CR061-S01:contract": dependency_digest},
        "cp6_result_ref": "process/checks/CP6-STORY-CR061-S02.result.json",
    }


def authorization_payload() -> dict[str, object]:
    return {
        "schema_version": 1, "cr_id": "CR-068", "story_id": "STORY-CR068-P01",
        "work_id": "WORK-1", "attempt_id": "attempt-1", "release_oid": "a" * 40,
        "process_oid": "b" * 40, "scope_digest": "c" * 64,
        "previous_cp6_ref": "process/checks/CP6-old.json", "previous_cp6_digest": "d" * 64,
        "superseding_cp5_ref": "process/checks/CP5-new.json", "superseding_cp5_digest": "e" * 64,
        "plan_preimage_digest": "f" * 64,
        "allowed_write_paths": ["process/works/WORK-1/revalidation/attempt-1/artifacts/**"],
    }


def revalidation_receipt_chain(
    *, cr_id: str = "CR-X", story_id: str = "STORY-X", work_id: str = "W-X",
    attempt_id: str = "attempt-chain-91ab",
) -> tuple[Cp6RevalidationReceiptV1, ...]:
    downstream_set = [
        {"producer": "producer-a", "receipt_digest": "a" * 64, "attempt_id": attempt_id},
    ]
    identity = {
        "cr_id": cr_id, "story_id": story_id, "work_id": work_id,
        "attempt_id": attempt_id, "release_oid": "b" * 40,
        "process_oid": "c" * 40, "scope_digest": "d" * 64,
    }
    authorization = build_cp6_revalidation_receipt(
        kind="authorization", **identity,
        payload={
            "previous_cp6_ref": "process/checks/previous.json",
            "superseding_cp5_ref": "process/checks/cp5.json",
            "approval_ref": "process/checkpoints/approval.json",
            "work_authorization_ref": "process/works/W-X/WORK.yaml",
            "plan_preimage_digest": "e" * 64,
            "downstream_set_digest": canonical_digest(downstream_set),
            "downstream_set": downstream_set,
        },
    )
    preflight = build_cp6_revalidation_receipt(
        kind="preflight", **identity,
        payload={
            "authorization_digest": authorization.as_dict()["payload_digest"],
            "packet_digest": "1" * 64, "read_log_digest": "2" * 64,
            "return_digest": "3" * 64, "evidence_digest": "4" * 64,
            "result_digest": "5" * 64, "checkpoint_digest": "6" * 64,
            "plan_digest": "7" * 64,
            "downstream_set_digest": canonical_digest(downstream_set),
            "p01_event_ref": "process/state/ledger.json",
        },
    )
    completion = build_cp6_revalidation_receipt(
        kind="completion", **identity,
        payload={
            "authorization_digest": authorization.as_dict()["payload_digest"],
            "preflight_digest": preflight.as_dict()["payload_digest"],
            "projection_digest": "8" * 64,
            "downstream_set_digest": canonical_digest(downstream_set),
        },
    )
    recovery = build_cp6_revalidation_receipt(
        kind="recovery", **identity,
        payload={
            "authorization_digest": authorization.as_dict()["payload_digest"],
            "completion_digest": completion.as_dict()["payload_digest"],
            "phase": "COMPLETE", "after_digest": "9" * 64,
        },
    )
    return authorization, preflight, completion, recovery


class FrozenCp6EvidenceTests(unittest.TestCase):
    def test_p01_v2_authorization_is_closed_and_admits_only_exact_ready_story(self) -> None:
        authorization = Cp6RevalidationAuthorizationV1.from_dict(authorization_payload())
        gate = {"story_id": "STORY-CR068-P01", "status": "ready-for-verification", "dev_gate": {}}
        identity = {key: getattr(authorization, key) for key in ("cr_id", "story_id", "work_id", "attempt_id", "release_oid", "process_oid", "scope_digest")}
        ready = project_story_admission(None, expected_dependency_digests={}, projected_gate=gate, revalidation_authorization=authorization, revalidation_identity=identity)
        self.assertEqual("READY", ready["decision"])
        blocked = project_story_admission(None, expected_dependency_digests={}, projected_gate=gate, revalidation_authorization={**authorization_payload(), "unknown": True}, revalidation_identity=identity)
        self.assertEqual("BLOCKED", blocked["decision"])

    def test_p01_v2_authorization_does_not_coerce_identity_types(self) -> None:
        payload = authorization_payload()
        payload["attempt_id"] = 1
        with self.assertRaisesRegex(FrozenCp6EvidenceError, "field types"):
            Cp6RevalidationAuthorizationV1.from_dict(payload)

    def test_p01_v2_authorization_rejects_unknown_missing_type_version_identity_ref_oid_and_digest(self) -> None:
        cases = (
            ("unknown", lambda payload: payload.__setitem__("unknown", True)),
            ("missing", lambda payload: payload.pop("attempt_id")),
            ("wrong-type", lambda payload: payload.__setitem__("scope_digest", 1)),
            ("bool-version", lambda payload: payload.__setitem__("schema_version", True)),
            ("unknown-version", lambda payload: payload.__setitem__("schema_version", 2)),
            ("unsafe-identity", lambda payload: payload.__setitem__("work_id", "../WORK")),
            ("unsafe-ref", lambda payload: payload.__setitem__("previous_cp6_ref", "process/checks/../CP6.json")),
            ("bad-release-oid", lambda payload: payload.__setitem__("release_oid", "A" * 40)),
            ("bad-process-oid", lambda payload: payload.__setitem__("process_oid", "not-an-oid")),
            ("bad-scope-digest", lambda payload: payload.__setitem__("scope_digest", "g" * 64)),
            ("bad-prior-digest", lambda payload: payload.__setitem__("previous_cp6_digest", "0" * 63)),
            ("bad-cp5-digest", lambda payload: payload.__setitem__("superseding_cp5_digest", "0" * 65)),
            ("bad-preimage", lambda payload: payload.__setitem__("plan_preimage_digest", "bad")),
            (
                "unsafe-allowlist",
                lambda payload: payload.__setitem__(
                    "allowed_write_paths",
                    ["process/works/WORK-1//revalidation/**"],
                ),
            ),
        )
        for name, mutate in cases:
            with self.subTest(name=name), self.assertRaises(FrozenCp6EvidenceError):
                payload = authorization_payload()
                mutate(payload)
                Cp6RevalidationAuthorizationV1.from_dict(payload)

    def test_p01_v2_authorization_capabilities_are_bound_to_exact_attempt_artifact_namespace(self) -> None:
        rejected = (
            ["process/works/**"],
            ["process/works/OTHER/revalidation/attempt-1/artifacts/**"],
            ["process/works/WORK-1/revalidation/other-attempt/artifacts/**"],
            ["process/works/WORK-1/revalidation/attempt-1/receipts/**"],
        )
        for capabilities in rejected:
            with self.subTest(capabilities=capabilities), self.assertRaises(FrozenCp6EvidenceError):
                payload = authorization_payload()
                payload["allowed_write_paths"] = capabilities
                Cp6RevalidationAuthorizationV1.from_dict(payload)

        accepted = (
            ["process/works/WORK-1/revalidation/attempt-1/artifacts/**"],
            [
                "process/works/WORK-1/revalidation/attempt-1/artifacts/STORY-CR068-P01.CP6.work-packet.json",
                "process/works/WORK-1/revalidation/attempt-1/artifacts/STORY-CR068-P01.CP6.return.json",
            ],
        )
        for capabilities in accepted:
            with self.subTest(capabilities=capabilities):
                payload = authorization_payload()
                payload["allowed_write_paths"] = capabilities
                authorization = Cp6RevalidationAuthorizationV1.from_dict(payload)
                self.assertEqual(capabilities, authorization.allowed_write_paths)

    def test_p01_v2_ready_for_verification_requires_exact_authorization_identity(self) -> None:
        authorization = Cp6RevalidationAuthorizationV1.from_dict(authorization_payload())
        gate = {
            "story_id": authorization.story_id,
            "status": "ready-for-verification",
            "dev_gate": {},
        }
        without_auth = project_story_admission(
            None,
            expected_dependency_digests={},
            projected_gate={
                "story_id": authorization.story_id,
                "status": "ready-for-verification",
                "dev_gate": {
                    "cp5_confirmed": True,
                    "dependencies_satisfied": True,
                    "file_conflict_free": True,
                    "implementation_authorized": True,
                    "lld_confirmed": True,
                },
            },
        )
        self.assertEqual("BLOCKED", without_auth["decision"])
        identity = {
            key: getattr(authorization, key)
            for key in (
                "cr_id", "story_id", "work_id", "attempt_id",
                "release_oid", "process_oid", "scope_digest",
            )
        }
        for field in identity:
            with self.subTest(field=field):
                candidate = dict(identity)
                candidate[field] = "0" * len(candidate[field])
                blocked = project_story_admission(
                    None,
                    expected_dependency_digests={},
                    projected_gate=gate,
                    revalidation_authorization=authorization,
                    revalidation_identity=candidate,
                )
                self.assertEqual("BLOCKED", blocked["decision"])
                self.assertEqual(
                    ["REVALIDATION_AUTHORIZATION_IDENTITY_MISMATCH"],
                    blocked["reason_codes"],
                )

    def test_p01_v2_normal_and_frozen_v1_admission_matrix_is_unchanged(self) -> None:
        normal_gate = {
            "story_id": "STORY-CR061-S04",
            "status": "dev-ready",
            "dev_gate": {
                "cp5_confirmed": True,
                "dependencies_satisfied": True,
                "file_conflict_free": True,
                "implementation_authorized": True,
                "lld_confirmed": True,
            },
        }
        self.assertEqual(
            "READY",
            project_story_admission(
                None,
                expected_dependency_digests={},
                projected_gate=normal_gate,
            )["decision"],
        )
        for field in normal_gate["dev_gate"]:
            with self.subTest(normal_field=field):
                blocked_gate = {
                    **normal_gate,
                    "dev_gate": {**normal_gate["dev_gate"], field: False},
                }
                self.assertEqual(
                    "BLOCKED",
                    project_story_admission(
                        None,
                        expected_dependency_digests={},
                        projected_gate=blocked_gate,
                    )["decision"],
                )
        expected = {"STORY-CR061-S01:contract": "a" * 64}
        valid = project_story_admission(evidence(), expected_dependency_digests=expected)
        missing = project_story_admission(None, expected_dependency_digests=expected)
        mismatch = project_story_admission(
            evidence(dependency_digest="b" * 64),
            expected_dependency_digests=expected,
        )
        self.assertEqual("READY", valid["decision"])
        self.assertEqual("BLOCKED", missing["decision"])
        self.assertEqual("revalidation-required", mismatch["decision"])

    def test_a003_pgr3_f001_schema_requires_chain_operation_not_fixture_policy(self) -> None:
        """PGR3-F001：真实 self-consistent receipt 不得依赖 schema 内 producer 特例。"""
        chain = revalidation_receipt_chain()
        result = frozen_cp6_evidence.validate_revalidation_receipt_chain(*chain)
        self.assertEqual("READY", result["decision"])
        for field in ("cr_id", "story_id", "work_id", "attempt_id"):
            changed = {field: "other"}
            cross = revalidation_receipt_chain(**changed)
            candidate = (*chain[:3], cross[3])
            blocked = frozen_cp6_evidence.validate_revalidation_receipt_chain(*candidate)
            self.assertEqual("BLOCKED", blocked["decision"])
            self.assertIn("REVALIDATION_CHAIN_IDENTITY_MISMATCH", blocked["reason_codes"])
        authorization, preflight, completion, recovery = chain
        links = (
            (1, "authorization_digest", "REVALIDATION_CHAIN_PREFLIGHT_AUTHORIZATION_MISMATCH"),
            (2, "authorization_digest", "REVALIDATION_CHAIN_COMPLETION_AUTHORIZATION_MISMATCH"),
            (2, "preflight_digest", "REVALIDATION_CHAIN_COMPLETION_PREFLIGHT_MISMATCH"),
            (2, "downstream_set_digest", "REVALIDATION_CHAIN_COMPLETION_DOWNSTREAM_SET_MISMATCH"),
            (3, "authorization_digest", "REVALIDATION_CHAIN_RECOVERY_AUTHORIZATION_MISMATCH"),
            (3, "completion_digest", "REVALIDATION_CHAIN_RECOVERY_COMPLETION_MISMATCH"),
        )
        for index, field, expected_reason in links:
            raw = list(chain[index].as_dict().items())
            changed = dict(raw)
            changed["payload"] = {**changed["payload"], field: "0" * 64}
            changed["payload_digest"] = canonical_digest({key: value for key, value in changed.items() if key != "payload_digest"})
            candidate = list(chain)
            candidate[index] = freeze_cp6_revalidation_receipt(**changed)
            blocked = frozen_cp6_evidence.validate_revalidation_receipt_chain(*candidate)
            self.assertEqual("BLOCKED", blocked["decision"])
            self.assertEqual([expected_reason], blocked["reason_codes"])
    # A3 mapping: TC01 schema, TC16 lineage, TC24 hardening;
    # COMP01 keeps FrozenCp6EvidenceV1 coverage in this module.
    def test_a3_tc01_rejects_escape_paths_and_tc16_rejects_downstream_lineage(self) -> None:
        payload = {
            "previous_cp6_ref": "process/checks/CP6-P01.json",
            "superseding_cp5_ref": "process/checks/CP5-P02.json",
            "approval_ref": "process/checkpoints/GATE.md",
            "work_authorization_ref": "process/works/W/WORK.yaml",
            "plan_preimage_digest": "d" * 64,
            "downstream_set_digest": "",
            "downstream_set": [{"producer": "I01", "receipt_digest": "f" * 64, "attempt_id": "attempt-1"}],
        }
        payload["downstream_set_digest"] = canonical_digest(payload["downstream_set"])
        valid = build_cp6_revalidation_receipt(
            kind="authorization", cr_id="CR-068", story_id="STORY-CR068-P02",
            work_id="CR-068-P02-IMPLEMENTATION-001", attempt_id="attempt-1",
            release_oid="a" * 40, process_oid="b" * 40, scope_digest="c" * 64,
            payload=payload,
        )
        self.assertEqual("authorization", valid.kind)
        for escaped in (
            "process/checkpoints/x/../../escape", "process/./escape", "process/a//b",
            "process\\escape", "/absolute/path", "",
        ):
            candidate = dict(payload)
            candidate["approval_ref"] = escaped
            with self.subTest(escaped=escaped), self.assertRaises(FrozenCp6EvidenceError):
                build_cp6_revalidation_receipt(
                    kind="authorization", cr_id="CR-068", story_id="STORY-CR068-P02",
                    work_id="CR-068-P02-IMPLEMENTATION-001", attempt_id="attempt-1",
                    release_oid="a" * 40, process_oid="b" * 40, scope_digest="c" * 64,
                    payload=candidate,
                )
        for field, value in (
            ("downstream_set_digest", "0" * 64),
            ("downstream_set", [{"producer": "I01", "receipt_digest": "f" * 64, "attempt_id": "other"}]),
        ):
            candidate = dict(payload)
            candidate[field] = value
            if field == "downstream_set":
                candidate["downstream_set_digest"] = canonical_digest(value)
            with self.subTest(field=field, value=value), self.assertRaises(FrozenCp6EvidenceError):
                build_cp6_revalidation_receipt(
                    kind="authorization", cr_id="CR-068", story_id="STORY-CR068-P02",
                    work_id="CR-068-P02-IMPLEMENTATION-001", attempt_id="attempt-1",
                    release_oid="a" * 40, process_oid="b" * 40, scope_digest="c" * 64,
                    payload=candidate,
                )

    def test_p02_revalidation_receipt_is_closed_and_digest_stable(self) -> None:
        downstream_set = [
            {"producer": "I01", "receipt_digest": "f" * 64, "attempt_id": "attempt-1"},
        ]
        receipt = build_cp6_revalidation_receipt(
            kind="authorization", cr_id="CR-068", story_id="STORY-CR068-P02",
            work_id="CR-068-P02-IMPLEMENTATION-001", attempt_id="attempt-1",
            release_oid="a" * 40, process_oid="b" * 40, scope_digest="c" * 64,
            payload={
                "previous_cp6_ref": "process/checks/CP6-P01.json",
                "superseding_cp5_ref": "process/checks/CP5-P02.json",
                "approval_ref": "process/checkpoints/GATE.md",
                "work_authorization_ref": "process/works/W/WORK.yaml",
                "plan_preimage_digest": "d" * 64,
                "downstream_set_digest": canonical_digest(downstream_set),
                "downstream_set": downstream_set,
            },
        )
        payload = receipt.as_dict()
        self.assertEqual(payload, freeze_cp6_revalidation_receipt(**payload).as_dict())
        payload["unknown"] = True
        with self.assertRaisesRegex(FrozenCp6EvidenceError, "fields mismatch"):
            Cp6RevalidationReceiptV1.from_dict(payload)

    def test_p02_revalidation_receipt_rejects_cross_lineage_and_bad_digest(self) -> None:
        chain = revalidation_receipt_chain()
        self.assertEqual("READY", frozen_cp6_evidence.validate_revalidation_receipt_chain(*chain)["decision"])
        receipt = chain[1].as_dict()
        receipt["payload_digest"] = "0" * 64
        with self.assertRaisesRegex(FrozenCp6EvidenceError, "payload_digest"):
            freeze_cp6_revalidation_receipt(**receipt)

    def test_a3_tc24_schema_mutations_fail_for_the_target_reason(self) -> None:
        """TC24：schema、closed fields、OID/SHA/ref/enum 分别独立失败。"""
        authorization, preflight, _completion, recovery = revalidation_receipt_chain()
        outer_cases = {
            "unknown-major": ({"schema_version": 99}, "unknown CP6 revalidation schema_version"),
            "unknown-kind": ({"kind": "unknown"}, "unknown CP6 revalidation receipt kind"),
            "bad-release-oid": ({"release_oid": "not-an-oid"}, "release_oid must be a lowercase 40-hex OID"),
            "bad-process-oid": ({"process_oid": "not-an-oid"}, "process_oid must be a lowercase 40-hex OID"),
            "bad-scope-sha": ({"scope_digest": "not-a-sha"}, "scope_digest must be a lowercase sha256 digest"),
        }
        for name, (mutation, reason) in outer_cases.items():
            raw = authorization.as_dict() | mutation
            raw["payload_digest"] = canonical_digest({key: value for key, value in raw.items() if key != "payload_digest"})
            with self.subTest(name=name), self.assertRaisesRegex(FrozenCp6EvidenceError, reason):
                freeze_cp6_revalidation_receipt(**raw)

        for name, mutate, reason in (
            ("outer-extra", lambda raw: raw.__setitem__("extra", True), "CP6 revalidation receipt fields mismatch"),
            ("outer-missing", lambda raw: raw.pop("work_id"), "CP6 revalidation receipt fields mismatch"),
            ("per-kind-extra", lambda raw: raw["payload"].__setitem__("extra", True), "authorization payload fields mismatch"),
            ("per-kind-missing", lambda raw: raw["payload"].pop("approval_ref"), "authorization payload fields mismatch"),
            ("bad-ref", lambda raw: raw["payload"].__setitem__("approval_ref", "process/../escape"), "approval_ref must be a process logical ref"),
        ):
            raw = authorization.as_dict()
            raw["payload"] = dict(raw["payload"])
            mutate(raw)
            if "payload_digest" in raw:
                raw["payload_digest"] = canonical_digest({key: value for key, value in raw.items() if key != "payload_digest"})
            with self.subTest(name=name), self.assertRaisesRegex(FrozenCp6EvidenceError, reason):
                freeze_cp6_revalidation_receipt(**raw)

        bad_enum = recovery.as_dict()
        bad_enum["payload"] = {**bad_enum["payload"], "phase": "UNKNOWN"}
        bad_enum["payload_digest"] = canonical_digest({key: value for key, value in bad_enum.items() if key != "payload_digest"})
        with self.assertRaisesRegex(FrozenCp6EvidenceError, "phase"):
            freeze_cp6_revalidation_receipt(**bad_enum)

        bad_preflight_sha = preflight.as_dict()
        bad_preflight_sha["payload"] = {**bad_preflight_sha["payload"], "packet_digest": "z" * 64}
        bad_preflight_sha["payload_digest"] = canonical_digest({key: value for key, value in bad_preflight_sha.items() if key != "payload_digest"})
        with self.assertRaisesRegex(FrozenCp6EvidenceError, "packet_digest"):
            freeze_cp6_revalidation_receipt(**bad_preflight_sha)
        for receipt in (authorization, preflight, _completion, recovery):
            for mutation in ("extra", "missing"):
                raw = receipt.as_dict()
                raw["payload"] = dict(raw["payload"])
                if mutation == "extra":
                    raw["payload"]["extra"] = True
                else:
                    raw["payload"].pop(next(iter(raw["payload"])))
                raw["payload_digest"] = canonical_digest({key: value for key, value in raw.items() if key != "payload_digest"})
                with self.subTest(kind=receipt.kind, mutation=mutation), self.assertRaisesRegex(FrozenCp6EvidenceError, "fields mismatch"):
                    freeze_cp6_revalidation_receipt(**raw)

    def test_c10_valid_v1_freezes_and_unknown_schema_blocks(self) -> None:
        frozen = freeze_cp6_evidence(**evidence())
        self.assertEqual(1, frozen.schema_version)
        payload = evidence()
        payload["schema_version"] = 2
        with self.assertRaises(FrozenCp6EvidenceError):
            freeze_cp6_evidence(**payload)

    def test_c11_unchanged_dependency_only_reconfirms(self) -> None:
        result = compare_frozen_evidence(evidence(), evidence())
        self.assertEqual("reconfirmed", result["decision"])
        self.assertEqual([], result["changed_dependencies"])

    def test_c12_changed_dependency_requires_downstream_revalidation(self) -> None:
        result = compare_frozen_evidence(evidence(), evidence(dependency_digest="b" * 64))
        self.assertEqual("revalidation-required", result["decision"])
        self.assertEqual(["STORY-CR061-S01:contract"], result["changed_dependencies"])

    def test_c13_virtual_bootstrap_never_forces_ready(self) -> None:
        result = project_story_admission(None, expected_dependency_digests={}, bootstrap={"force_ready": True})
        self.assertEqual("BLOCKED", result["decision"])
        self.assertIn("FROZEN_CP6_EVIDENCE_MISSING", result["reason_codes"])

    def test_native_development_plan_gate_is_the_only_first_admission_ready_path(self) -> None:
        projected_gate = {
            "story_id": "STORY-CR061-S04",
            "status": "dev-ready",
            "dev_gate": {
                "cp5_confirmed": True,
                "dependencies_satisfied": True,
                "file_conflict_free": True,
                "implementation_authorized": True,
                "lld_confirmed": True,
            },
        }
        result = project_story_admission(
            None,
            expected_dependency_digests={},
            projected_gate=projected_gate,
        )
        self.assertEqual("READY", result["decision"])
        self.assertEqual(["NATIVE_DEVELOPMENT_PLAN_GATE_READY"], result["reason_codes"])

    def test_native_development_plan_gate_blocks_unknown_shape_or_false_gate(self) -> None:
        projected_gate = {
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
        blocked = project_story_admission(
            None,
            expected_dependency_digests={},
            projected_gate=projected_gate,
        )
        self.assertEqual("BLOCKED", blocked["decision"])
        invalid = project_story_admission(
            None,
            expected_dependency_digests={},
            projected_gate={**projected_gate, "unknown": True},
        )
        self.assertEqual(["NATIVE_PLAN_GATE_INVALID"], invalid["reason_codes"])

    def test_c14_single_and_batch_project_same_decision_bytes(self) -> None:
        expected = {"STORY-CR061-S01:contract": "a" * 64}
        single = project_story_admission(evidence(), expected_dependency_digests=expected)
        batch = project_story_admissions(
            {"STORY-CR061-S02": evidence()},
            expected_dependency_digests_by_story={"STORY-CR061-S02": expected},
        )["STORY-CR061-S02"]
        self.assertEqual(
            json.dumps(single, sort_keys=True, separators=(",", ":")).encode(),
            json.dumps(batch, sort_keys=True, separators=(",", ":")).encode(),
        )

    def test_c14_batch_projection_has_stable_story_id_order(self) -> None:
        projected = project_story_admissions(
            {"STORY-Z": None, "STORY-A": None},
            expected_dependency_digests_by_story={"STORY-Z": {}, "STORY-A": {}},
        )
        self.assertEqual(["STORY-A", "STORY-Z"], list(projected))
