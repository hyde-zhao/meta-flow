"""CAC-07：P6 closure plan/apply/recover（IF-10..12）——blockers 矩阵、partial journal、幂等续跑。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from conftest import (
    D64,
    OID40,
    import_pair,
    installation_receipt,
    publication_receipt,
    verified_observation,
    write_yaml,
)

from meta_flow.execution_control.contract import ExecutionUnitV1
from meta_flow.release import close_plan as close_plan_module
from meta_flow.release.close_plan import (
    ATTESTATION_BINDING_MISMATCH,
    CLOSURE_TARGET_MISSING,
    JOURNAL_NAME,
    P6_CLOSURE_BLOCKED,
    PLAN_DRIFTED,
    TERMINAL_ALREADY_EXISTS,
    VARIANT_CARDINALITY_VIOLATED,
    VARIANT_IDENTITY_DIVERGED,
    VARIANT_ORDER_VIOLATED,
    P6ClosureAuthorizationV1,
    P6ClosureBlocked,
    apply_p6_closure,
    plan_p6_closure,
    recover_p6_closure,
)
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.model import build_work
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root

CR_ID = "CR-076"


def _p(process: Path, ref: str) -> Path:
    """逻辑 ref（process/...）→ 物理路径。"""
    return process / Path(ref).relative_to("process")


def _git_commit_all(root: Path, message: str) -> None:
    import subprocess

    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Meta Flow Test", "-c", "user.email=meta-flow@example.invalid", "commit", "-m", message],
        cwd=root, check=True, capture_output=True,
    )


def _make_work(process: Path, work_id: str):
    request_ref = f"works/{work_id}/REQUEST.md"
    (process / request_ref).parent.mkdir(parents=True, exist_ok=True)
    (process / request_ref).write_text("# 请求\n\n用户确认：是。\n", encoding="utf-8")
    work = replace(
        build_work(
            work_id=work_id,
            project_id="demo",
            objective="P6 收口测试 Work",
            request_ref=request_ref,
            scope=WorkScope(
                version=1,
                allowed_reads=(request_ref,),
                allowed_writes=(f"works/{work_id}/",),
                required_checks=(),
            ),
            classification=classify_work(RiskFacts(change_kind="documentation", touched_path_count=1)),
            release_base_oid=OID40,
            process_base_oid="",
            phase_ref="",
        ),
        execution_unit=ExecutionUnitV1(
            unit_id=work_id, root_concept="work-close", slice_id=work_id, container_role="primary",
            revision=1, supersedes_unit_id="", contract_ref=request_ref, contract_digest="c" * 64,
        ),
    )
    return work


@pytest.fixture()
def closure_env(routed):
    """B1+B2 归档 + ready guard 对象 + active Work + CR md；返回全部 plan 输入。"""
    release, process = routed
    _git_commit_all(process, "initial process")  # work init 需要 repository OID 可用
    _, r2, _, _ = import_pair(release, process)
    archive = Path(r2.archive_path).parent
    attestation = yaml.safe_load((archive / "attestation.yaml").read_bytes())
    attestation_ref = f"process/evidence/CR-076/consumer-acceptance/{archive.name}/attestation.yaml"
    b1_ref = "process/evidence/CR-076/consumer-acceptance/CAR-076-SCN076-07-R1"
    b2_ref = f"process/evidence/CR-076/consumer-acceptance/{archive.name}"
    observation = verified_observation(attestation["attestation_digest"])
    observation_ref = write_yaml(process, "evidence/CR-076/observation.yaml", observation)
    receipts = (publication_receipt(attestation["attestation_digest"]),)
    for work_id in ("W-P6-A", "W-P6-B"):
        work = _make_work(process, work_id)
        apply_work_init(plan_work_init_from_release_root(release, work))
        update_work_status(process, work_id, expected_status="planned", new_status="active")
        result_ref = f"works/{work_id}/RESULT.json"
        (process / result_ref).write_text(
            json.dumps({"schema_version": 1, "work_id": work_id, "decision": "PASS"}) + "\n", encoding="utf-8"
        )
    (process / "changes").mkdir(exist_ok=True)
    (process / "changes" / f"{CR_ID}.md").write_text(f"# {CR_ID}\n\nP6 closure 测试 CR。\n", encoding="utf-8")
    return {
        "release": release, "process": process, "attestation_ref": attestation_ref,
        "b1_ref": b1_ref, "b2_ref": b2_ref, "observation": observation,
        "observation_ref": observation_ref, "receipts": receipts,
        "installation": installation_receipt(), "work_ids": ("W-P6-A", "W-P6-B"), "cr_id": CR_ID,
    }


def _plan(env, **overrides):
    kwargs = dict(
        replay_result_refs=(env["b1_ref"], env["b2_ref"]),
        attestation_ref=env["attestation_ref"],
        publication_receipts=env["receipts"],
        observation_ref=env["observation_ref"],
        installation_receipt=env["installation"],
        cr_id=env["cr_id"],
        work_ids=env["work_ids"],
        dq06_baseline_statement="DQ06 基线结转声明",
    )
    kwargs.update(overrides)
    return plan_p6_closure(env["release"], **kwargs)


def _authorization(plan):
    return P6ClosureAuthorizationV1(
        1, "p6-closure-authorization-v1", "AZ-P6-CLOSE-0001", plan.plan_digest,
        str(plan.inputs.get("cr_id") or ""), tuple(plan.inputs.get("work_ids") or ()),
        "2099-01-01T00:00:00+00:00", True,
    )


class TestPlanP6Closure:
    def test_happy_plan_ready_and_digest_stable(self, closure_env):
        plan = _plan(closure_env)
        assert plan.ready and plan.blockers == ()
        assert set(plan.inputs) >= {"b1_result_ref", "b2_result_ref", "attestation_ref", "observation_ref", "cr_id", "work_ids"}
        assert _plan(closure_env).plan_digest == plan.plan_digest  # fresh_at 不参与 digest
        assert plan.precheck["stale_refs_count"] == 0

    def test_cardinality_missing_b2(self, closure_env):
        plan = _plan(closure_env, replay_result_refs=(closure_env["b1_ref"],))
        assert not plan.ready and VARIANT_CARDINALITY_VIOLATED in plan.blockers

    def test_cardinality_duplicate_variant(self, closure_env):
        env = closure_env
        extra = env["process"] / "evidence" / "CR-076" / "consumer-acceptance" / "CAR-076-SCN076-07-R1X"
        source = _p(env["process"], env["b1_ref"])
        extra.mkdir(parents=True)
        for name in ("result.json", "ingestion-receipt.yaml"):
            (extra / name).write_bytes((source / name).read_bytes())
        plan = _plan(env, replay_result_refs=(env["b1_ref"], env["b2_ref"], "process/evidence/CR-076/consumer-acceptance/CAR-076-SCN076-07-R1X"))
        assert VARIANT_CARDINALITY_VIOLATED in plan.blockers

    def test_order_violated(self, closure_env):
        env = closure_env
        receipt_path = _p(env["process"], env["b2_ref"]) / "ingestion-receipt.yaml"
        receipt = yaml.safe_load(receipt_path.read_bytes())
        receipt["imported_at"] = "2020-01-01T00:00:00Z"  # B2 早于 B1
        receipt_path.write_text(yaml.safe_dump(receipt, sort_keys=True), encoding="utf-8")
        plan = _plan(env)
        assert VARIANT_ORDER_VIOLATED in plan.blockers

    def test_identity_diverged(self, closure_env):
        env = closure_env
        result_path = _p(env["process"], env["b1_ref"]) / "result.json"
        payload = json.loads(result_path.read_bytes())
        payload["artifact"]["source_release_oid"] = "9" * 40  # B1 与 B2 来源分裂（guard 只看 B2 不受影响）
        result_path.write_text(json.dumps(payload), encoding="utf-8")
        plan = _plan(env)
        assert VARIANT_IDENTITY_DIVERGED in plan.blockers

    def test_guard_not_ready_maps_to_binding_mismatch(self, closure_env):
        env = closure_env
        stale = dict(env["observation"], valid_until="2020-01-01T00:00:00Z")
        env["observation_ref"] = write_yaml(env["process"], "evidence/CR-076/observation.yaml", stale)
        plan = _plan(env)
        assert ATTESTATION_BINDING_MISMATCH in plan.blockers

    def test_work_missing_blocks(self, closure_env):
        plan = _plan(closure_env, work_ids=("W-NOPE",))
        assert CLOSURE_TARGET_MISSING in plan.blockers

    def test_cr_missing_blocks(self, closure_env):
        plan = _plan(closure_env, cr_id="CR-999")
        assert CLOSURE_TARGET_MISSING in plan.blockers


class TestApplyP6Closure:
    def _cr_fake(self, monkeypatch):
        calls = []

        def fake_close_cr(project_root, cr_id, **kwargs):
            calls.append((cr_id, kwargs.get("readiness")))
            return {"cr": Path("changes") / f"{cr_id}.md"}

        monkeypatch.setattr(close_plan_module, "close_cr", fake_close_cr)
        return calls

    def test_success_chain_writes_terminal(self, closure_env, monkeypatch):
        env = closure_env
        plan = _plan(env)
        cr_calls = self._cr_fake(monkeypatch)
        terminal = apply_p6_closure(
            env["release"], plan, _authorization(plan),
            publication_receipts=env["receipts"], installation_receipt=env["installation"],
            work_close_inputs={
                "W-P6-A": {"expected_status": "active", "outcome": "completed", "result_ref": "works/W-P6-A/RESULT.json"},
                "W-P6-B": {"expected_status": "active", "outcome": "completed", "result_ref": "works/W-P6-B/RESULT.json"},
            },
            cr_close_input={"readiness": "READY", "work_id": "W-P6-B", "effective_at": "2026-09-01T00:00:00Z",
                            "expected_process_oid": "", "expected_plan_digest": "", "authorization": None},
        )
        assert list(terminal.closed_work_ids) == ["W-P6-A", "W-P6-B"]
        assert list(terminal.closed_cr_ids) == [CR_ID]
        assert terminal.active_zero_proof is True
        assert terminal.stale_zero_proof is True
        assert terminal.phase_transition_precheck == "not-executed"
        assert cr_calls == [(CR_ID, "READY")]
        terminal_path = env["process"] / "evidence" / "CR-076" / "p6-closure" / "P6-TERMINAL-RESULT.yaml"
        assert terminal_path.is_file()
        persisted = yaml.safe_load(terminal_path.read_bytes())
        assert persisted["result_digest"] == terminal.result_digest
        assert not (terminal_path.parent / JOURNAL_NAME).exists()  # 无 partial 即无 journal

    def test_authorization_mismatch_rejected(self, closure_env):
        env = closure_env
        plan = _plan(env)
        wrong = P6ClosureAuthorizationV1(
            1, "p6-closure-authorization-v1", "AZ-X", "f" * 64,
            env["cr_id"], tuple(env["work_ids"]), "2099-01-01T00:00:00+00:00", True,
        )
        with pytest.raises(ValueError):
            apply_p6_closure(
                env["release"], plan, wrong,
                publication_receipts=env["receipts"], installation_receipt=env["installation"],
                work_close_inputs={}, cr_close_input={},
            )

    def test_not_ready_plan_rejected(self, closure_env):
        env = closure_env
        plan = _plan(env, work_ids=("W-NOPE",))
        assert not plan.ready
        with pytest.raises(P6ClosureBlocked) as excinfo:
            apply_p6_closure(
                env["release"], plan, _authorization(plan),
                publication_receipts=env["receipts"], installation_receipt=env["installation"],
                work_close_inputs={}, cr_close_input={},
            )
        assert excinfo.value.code == P6_CLOSURE_BLOCKED

    def test_plan_drifted_when_archive_mutates(self, closure_env):
        env = closure_env
        plan = _plan(env)
        stale = dict(env["observation"], valid_until="2020-01-01T00:00:00Z")  # 授权后输入漂移
        write_yaml(env["process"], "evidence/CR-076/observation.yaml", stale)
        with pytest.raises(P6ClosureBlocked) as excinfo:
            apply_p6_closure(
                env["release"], plan, _authorization(plan),
                publication_receipts=env["receipts"], installation_receipt=env["installation"],
                work_close_inputs={}, cr_close_input={},
            )
        assert excinfo.value.code == PLAN_DRIFTED

    def test_terminal_already_exists_rejected(self, closure_env, monkeypatch):
        env = closure_env
        plan = _plan(env)
        terminal_dir = env["process"] / "evidence" / "CR-076" / "p6-closure"
        terminal_dir.mkdir(parents=True, exist_ok=True)
        (terminal_dir / "P6-TERMINAL-RESULT.yaml").write_text("kind: P6TerminalResultV1\n", encoding="utf-8")
        with pytest.raises(P6ClosureBlocked) as excinfo:
            apply_p6_closure(
                env["release"], plan, _authorization(plan),
                publication_receipts=env["receipts"], installation_receipt=env["installation"],
                work_close_inputs={}, cr_close_input={},
            )
        assert excinfo.value.code == TERMINAL_ALREADY_EXISTS

    def test_partial_closure_journals_and_retry_resumes(self, closure_env, monkeypatch):
        env = closure_env
        plan = _plan(env)
        real_apply = close_plan_module.apply_work_close

        def failing_apply(process_root, work_plan, authorization):
            if work_plan.work_id == "W-P6-B":
                raise RuntimeError("injected close failure")
            return real_apply(process_root, work_plan, authorization)

        monkeypatch.setattr(close_plan_module, "apply_work_close", failing_apply)
        with pytest.raises(P6ClosureBlocked) as excinfo:
            apply_p6_closure(
                env["release"], plan, _authorization(plan),
                publication_receipts=env["receipts"], installation_receipt=env["installation"],
                work_close_inputs={
                    "W-P6-A": {"expected_status": "active", "outcome": "completed", "result_ref": "works/W-P6-A/RESULT.json"},
                    "W-P6-B": {"expected_status": "active", "outcome": "completed", "result_ref": "works/W-P6-B/RESULT.json"},
                },
                cr_close_input={"readiness": "READY", "work_id": "W-P6-B", "effective_at": "2026-09-01T00:00:00Z",
                                "expected_process_oid": "", "expected_plan_digest": "", "authorization": None},
            )
        assert excinfo.value.code == P6_CLOSURE_BLOCKED
        # journal 记录 completed/remaining（W-P6-A 已 close 不回滚）
        inspection = recover_p6_closure(env["release"])
        assert inspection.completed_refs == ("W-P6-A",)
        assert inspection.remaining_refs == ("W-P6-B", CR_ID)
        assert "injected close failure" in inspection.last_error
        # W-P6-A 已 native close（无重复 close 面）
        from meta_flow.work.model import load_work

        assert load_work(env["process"], "W-P6-A").status == "completed"
        # 幂等续跑：fresh plan 只携带 remaining 对象 → 只 close W-P6-B + CR → terminal
        retry_env = dict(env, work_ids=("W-P6-B",))
        retry_plan = _plan(retry_env)
        assert retry_plan.ready
        self._cr_fake(monkeypatch)
        monkeypatch.setattr(close_plan_module, "apply_work_close", real_apply)
        terminal = apply_p6_closure(
            env["release"], retry_plan, _authorization(retry_plan),
            publication_receipts=env["receipts"], installation_receipt=env["installation"],
            work_close_inputs={"W-P6-B": {"expected_status": "active", "outcome": "completed", "result_ref": "works/W-P6-B/RESULT.json"}},
            cr_close_input={"readiness": "READY", "work_id": "W-P6-B", "effective_at": "2026-09-01T00:00:00Z",
                            "expected_process_oid": "", "expected_plan_digest": "", "authorization": None},
        )
        assert list(terminal.closed_work_ids) == ["W-P6-B"]
        assert terminal.active_zero_proof is True
        # 再次整体重放（同原始 plan）→ 拒绝：fresh precheck 的 active 集合已漂移（双 work 已
        # completed），PLAN_DRIFTED 先于 terminal 存在性检查 → 无 false terminal、无二次收口
        with pytest.raises(P6ClosureBlocked) as again:
            apply_p6_closure(
                env["release"], plan, _authorization(plan),
                publication_receipts=env["receipts"], installation_receipt=env["installation"],
                work_close_inputs={}, cr_close_input={},
            )
        assert again.value.code == PLAN_DRIFTED


class TestRecoverP6Closure:
    def test_empty_journal_reports_nothing(self, closure_env):
        inspection = recover_p6_closure(closure_env["release"])
        assert inspection.entries == ()
        assert inspection.completed_refs == () and inspection.remaining_refs == ()
        assert inspection.last_error == ""


class TestCliExitCodeContract:
    """IF-13 命令冒烟：退出码 0=PASS / 2=BLOCKED（治理阻断不得降级为软失败）。"""

    def test_import_blocked_returns_two(self, closure_env, capsys):
        from meta_flow.release import cli as release_cli

        env = closure_env
        frozen = {
            "variant": "installed-artifact-replay", "source_release_oid": OID40, "source_process_oid": OID40,
            "provider_identity": "provider-authoritative-dev", "consumer_project_uid": "consumer-project-uid-1",
            "quant_lab_release_oid": OID40, "quant_lab_process_oid": OID40,
            "command_identity": "meta-flow replay execute --scenario SCN-076-07",
            "profile_fingerprint": D64, "environment_fingerprint": D64, "provider_fingerprint": D64,
            "bundle_manifest_digest": D64, "semver": "1.2.3", "wheel_digest": D64, "sdist_digest": D64,
            "bundle_receipt_digest": D64, "sidecar_digest": D64, "artifact_provider_fingerprint": D64,
        }
        rc = release_cli.main(
            ["consumer-acceptance-import", "--project-root", str(env["release"]),
             "--result-ref", "process/evidence/CR-076/consumer-acceptance/CAR-076-SCN076-07-R2/result.json",
             "--variant", "installed-artifact-replay", "--frozen-identity", json.dumps(frozen),
             "--authorization-evidence", json.dumps({}), "--provenance", json.dumps({"issuance_rows": []}),
             "--installation-predecessor", json.dumps(installation_receipt()), "--authorization-id", "AZ-CLI"]
        )
        assert rc == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["decision"] == "BLOCKED"

    def test_p6_plan_blocked_returns_two_and_recover_passes(self, closure_env, capsys):
        from meta_flow.release import cli as release_cli

        env = closure_env
        rc = release_cli.main(
            ["p6-closure", "--project-root", str(env["release"]), "--mode", "plan",
             "--replay-result-refs", env["b1_ref"], env["b2_ref"],
             "--attestation-ref", env["attestation_ref"], "--observation-ref", env["observation_ref"],
             "--publication-receipt", json.dumps(env["receipts"][0]),
             "--installation-receipt", json.dumps(env["installation"]),
             "--cr-id", env["cr_id"], "--work-id", "W-P6-A"]
        )
        assert rc == 0  # closure_env 内 guard 链就绪且 Work 存在 → plan ready
        capsys.readouterr()  # 清空 plan 输出
        rc = release_cli.main(
            ["p6-closure", "--project-root", str(env["release"]), "--mode", "plan",
             "--replay-result-refs", env["b1_ref"], env["b2_ref"],
             "--attestation-ref", env["attestation_ref"], "--observation-ref", env["observation_ref"],
             "--publication-receipt", json.dumps(env["receipts"][0]),
             "--installation-receipt", json.dumps(env["installation"]),
             "--cr-id", "CR-NOPE", "--work-id", "W-P6-A"]
        )
        assert rc == 2  # CLOSURE-TARGET-MISSING → BLOCKED
        capsys.readouterr()
        rc = release_cli.main(
            ["p6-closure", "--project-root", str(env["release"]), "--mode", "recover",
             "--replay-result-refs", "x", "--attestation-ref", "x", "--observation-ref", "x",
             "--publication-receipt", "{}", "--installation-receipt", "{}", "--cr-id", env["cr_id"]]
        )
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["completed_refs"] == []

    def test_unknown_release_command_returns_two(self, capsys):
        from meta_flow.release import cli as release_cli

        assert release_cli.main(["no-such"]) == 2
        assert release_cli.main([]) == 0
