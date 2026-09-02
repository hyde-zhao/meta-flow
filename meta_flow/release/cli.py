"""release 组 CLI：CR-076 S05 IF-13（consumer-acceptance-import / p6-closure）。

退出码契约：0=PASS；2=BLOCKED（LLD §6 IF-13）。plan 未 ready 也是治理性阻断（2），
与 work 组的 0/1 软失败口径区分；BLOCKED 输出机器 JSON（零 traceback）。
R4 返修：授权信任根 = S02 持久双账本（root/.meta-flow-runtime/authorization/），
跨进程 single-use 可验证；不再使用进程内存账本。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from meta_flow.execution_control.authorization import AuthorizationBlockedError
from meta_flow.ingestion.consumer_acceptance_import import AUTHORIZATION_ISSUANCE_MISSING
from meta_flow.ingestion.consumer_acceptance_schema import ConsumerAcceptanceBlocked
from meta_flow.release.close_plan import (
    P6ClosureBlocked,
    apply_p6_closure,
    plan_p6_closure,
    recover_p6_closure,
)

EXIT_PASS = 0
EXIT_BLOCKED = 2


def _variant(value: str) -> str:
    from meta_flow.ingestion.consumer_acceptance_validator import (
        INSTALLED_ARTIFACT,
        SOURCE_CANDIDATE,
    )

    if value not in (SOURCE_CANDIDATE, INSTALLED_ARTIFACT):
        raise argparse.ArgumentTypeError(f"unknown variant: {value!r}")
    return value


def _emit(payload: dict[str, Any], *, pass_through: bool) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_PASS if pass_through else EXIT_BLOCKED


def _blocked(kind: str, **fields: Any) -> int:
    return _emit({"schema_version": 1, "kind": kind, "decision": "BLOCKED", **fields}, pass_through=False)


def _load_json_argument(raw: str, *, label: str) -> dict[str, Any]:
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def _rows(raw: Any) -> tuple[dict[str, Any], ...] | None:
    """issuance_rows 三态：键缺失=None（registry 不可达）；[]/列表=显式行集。"""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("provenance.issuance_rows must be a list or null")
    return tuple(raw)


class PersistentAuthorizationLedger:
    """S02 双账本适配器：实现 ingestion 的 AuthorizationLedger 窄协议（O-03）。

    is_consumed/consume 全部委托 meta_flow.execution_control.authorization.
    AuthorizationLedger（root/.meta-flow-runtime/authorization/ 双 append-only
    ndjson），跨进程 single-use 可验证；每次 CLI 调用从磁盘状态新建实例，
    零进程内共享内存。issuance 未登记 → AUTHORIZATION-ISSUANCE-MISSING
    （确定性阻断，交给 consume 显式暴露而非 is_consumed 误报）。
    """

    def __init__(self, root: Path) -> None:
        from meta_flow.execution_control.authorization import (
            AuthorizationLedger as S02AuthorizationLedger,
        )

        self._ledger = S02AuthorizationLedger(root=Path(root).resolve())

    def _resolve_envelope(self, authorization_id: str):
        from meta_flow.execution_control.authorization import (
            parse_authorization_envelope,
        )

        document = self._ledger.lookup_issuance_document(authorization_id)
        if document is None:
            raise ConsumerAcceptanceBlocked(
                AUTHORIZATION_ISSUANCE_MISSING,
                f"authorization not found in issuance registry: {authorization_id}",
            )
        # registry 存储的 target_refs 是 list；parse 内部完成闭合校验并 tuple 化。
        return parse_authorization_envelope(document)

    def is_consumed(self, authorization_id: str) -> bool:
        from meta_flow.execution_control.authorization import (
            authorization_digest,
            parse_authorization_envelope,
        )

        document = self._ledger.lookup_issuance_document(authorization_id)
        if document is None:
            return False
        return bool(self._ledger.attempts(authorization_digest(parse_authorization_envelope(document))))

    def consume(self, authorization_id: str, *, attempt_id: str, preimage_digest: str) -> None:
        envelope = self._resolve_envelope(authorization_id)
        self._ledger.consume(
            envelope,
            attempt_id=attempt_id,
            preimage_digests={"result.json": preimage_digest},
        )


def consumer_acceptance_import_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow release consumer-acceptance-import")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--result-ref", required=True, help="回传 result 逻辑 ref（process/...）")
    parser.add_argument("--variant", type=_variant, required=True)
    parser.add_argument("--frozen-identity", required=True, help="ProviderFrozenIdentityV1 JSON")
    parser.add_argument("--authorization-evidence", required=True, help="授权证据 JSON")
    parser.add_argument("--provenance", required=True, help='{"issuance_rows": [...], ...} JSON')
    parser.add_argument("--installation-predecessor", default="", help="B2 必填 InstallationReceiptV1 JSON")
    parser.add_argument("--authorization-id", required=True)
    args = parser.parse_args(argv)
    try:
        from meta_flow.ingestion.consumer_acceptance_import import (
            DECISION_IMPORTED,
            import_consumer_acceptance,
        )
        from meta_flow.ingestion.consumer_acceptance_validator import (
            ProvenanceBundle,
            ProviderFrozenIdentityV1,
        )

        frozen = ProviderFrozenIdentityV1(**_load_json_argument(args.frozen_identity, label="frozen-identity"))
        evidence = _load_json_argument(args.authorization_evidence, label="authorization-evidence")
        provenance_payload = _load_json_argument(args.provenance, label="provenance")
        provenance = ProvenanceBundle(
            issuance_rows=_rows(provenance_payload.get("issuance_rows")),
            execution_ledger_rows=tuple(provenance_payload.get("execution_ledger_rows") or ()),
            frozen_public_key=str(provenance_payload.get("frozen_public_key") or ""),
            preregistered_challenges=tuple(provenance_payload.get("preregistered_challenges") or ()),
        )
        predecessor = (
            _load_json_argument(args.installation_predecessor, label="installation-predecessor")
            if args.installation_predecessor
            else None
        )
        receipt = import_consumer_acceptance(
            args.project_root,
            result_ref=args.result_ref,
            frozen=frozen,
            authorization_evidence=evidence,
            provenance=provenance,
            ledger=PersistentAuthorizationLedger(args.project_root),
            authorization_id=args.authorization_id,
            installation_predecessor=predecessor,
        )
        # R3 返修：IngestionReceipt 是 frozen dataclass（document/digest/attestation/
        # archive_path/receipt_path），无 as_dict/decision；成功路径输出 document 展开。
        document = dict(receipt.document)
        return _emit(
            {
                "schema_version": 1,
                **document,
                "archive_path": str(receipt.archive_path),
                "receipt_path": str(receipt.receipt_path),
                "attestation": dict(receipt.attestation) if receipt.attestation is not None else None,
            },
            pass_through=str(document.get("decision") or "") == DECISION_IMPORTED,
        )
    except ConsumerAcceptanceBlocked as exc:
        return _blocked("ConsumerAcceptanceImportReceiptV1", error=f"{exc.code}: {exc.detail}")
    except AuthorizationBlockedError as exc:
        # S02 账本侧确定性阻断（过期/已消费/前驱缺失等）：同样零 traceback、exit 2。
        return _blocked("ConsumerAcceptanceImportReceiptV1", error=f"{exc.code}: {exc.detail}")
    except (OSError, ValueError, TypeError) as exc:
        return _blocked("ConsumerAcceptanceImportReceiptV1", error=str(exc))


def p6_closure_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow release p6-closure")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=("plan", "apply", "recover"), required=True)
    parser.add_argument("--replay-result-refs", nargs="+", required=True, help="B1/B2 归档目录逻辑 ref")
    parser.add_argument("--attestation-ref", required=True)
    parser.add_argument("--observation-ref", required=True)
    parser.add_argument("--publication-receipt", action="append", default=[], help="PublicationReceiptV1 JSON（可多次）")
    parser.add_argument("--installation-receipt", required=True, help="InstallationReceiptV1 JSON")
    parser.add_argument("--cr-id", required=True)
    parser.add_argument("--work-id", action="append", default=[], help="待收口 Work（可多次）")
    parser.add_argument("--dq06-baseline-statement", default="")
    parser.add_argument("--apply", action="store_true", help="mode=apply 时执行（否则仅输出 plan）")
    parser.add_argument("--authorization", default="", help="P6ClosureAuthorizationV1 JSON")
    parser.add_argument("--work-close-inputs", default="{}", help='{"W-ID": {"result_ref": ...}} JSON')
    parser.add_argument("--cr-close-input", default="{}", help="close_cr 关键字 JSON")
    args = parser.parse_args(argv)
    try:
        receipts = tuple(_load_json_argument(item, label="publication-receipt") for item in args.publication_receipt)
        installation = _load_json_argument(args.installation_receipt, label="installation-receipt")
        if args.mode == "recover":
            inspection = recover_p6_closure(args.project_root)
            return _emit(
                {
                    "schema_version": 1,
                    "kind": "P6ClosureRecoveryInspectionV1",
                    "journal_ref": inspection.journal_ref,
                    "entries": [dict(entry) for entry in inspection.entries],
                    "completed_refs": list(inspection.completed_refs),
                    "remaining_refs": list(inspection.remaining_refs),
                    "last_error": inspection.last_error,
                },
                pass_through=True,
            )
        if not args.work_id:
            raise ValueError("p6-closure requires at least one --work-id")
        plan = plan_p6_closure(
            args.project_root,
            replay_result_refs=tuple(args.replay_result_refs),
            attestation_ref=args.attestation_ref,
            publication_receipts=receipts,
            observation_ref=args.observation_ref,
            installation_receipt=installation,
            fu_candidates=(),
            cr_id=args.cr_id,
            work_ids=tuple(args.work_id),
            dq06_baseline_statement=args.dq06_baseline_statement,
        )
        if args.mode == "plan":
            return _emit(
                {
                    "schema_version": 1,
                    "kind": "P6ClosurePlanV1",
                    "plan_id": plan.plan_id,
                    "ready": plan.ready,
                    "blockers": list(plan.blockers),
                    "plan_digest": plan.plan_digest,
                    "inputs": dict(plan.inputs),
                    "precheck": dict(plan.precheck),
                },
                pass_through=plan.ready,
            )
        # mode=apply：fresh 重验 + 授权绑定；输入漂移/未就绪=BLOCKED
        if not args.apply:
            raise ValueError("p6-closure --mode apply requires --apply")
        if not args.authorization:
            raise ValueError("p6-closure --apply requires --authorization")
        from meta_flow.release.close_plan import P6ClosureAuthorizationV1

        authorization = P6ClosureAuthorizationV1(**_load_json_argument(args.authorization, label="authorization"))
        work_close_inputs = _load_json_argument(args.work_close_inputs, label="work-close-inputs")
        cr_close_input = _load_json_argument(args.cr_close_input, label="cr-close-input")
        terminal = apply_p6_closure(
            args.project_root,
            plan,
            authorization,
            publication_receipts=receipts,
            installation_receipt=installation,
            work_close_inputs=work_close_inputs,
            cr_close_input=cr_close_input,
        )
        return _emit(
            {
                "schema_version": 1,
                "kind": "P6TerminalResultV1",
                "terminal_id": terminal.terminal_id,
                "plan_digest": terminal.plan_digest,
                "closed_cr_ids": list(terminal.closed_cr_ids),
                "closed_work_ids": list(terminal.closed_work_ids),
                "active_zero_proof": terminal.active_zero_proof,
                "stale_zero_proof": terminal.stale_zero_proof,
                "result_digest": terminal.result_digest,
            },
            pass_through=terminal.active_zero_proof and terminal.stale_zero_proof,
        )
    except P6ClosureBlocked as exc:
        return _blocked("P6ClosureBlockedV1", code=exc.code, detail=exc.detail)
    except (OSError, ValueError, TypeError) as exc:
        return _blocked("P6ClosureBlockedV1", code="P6-CLOSURE-BLOCKED", detail=str(exc))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in {"-h", "--help"}:
        print("usage: meta-flow release <consumer-acceptance-import | p6-closure> ...")
        return EXIT_PASS
    command = args[0]
    if command == "consumer-acceptance-import":
        return consumer_acceptance_import_main(args[1:])
    if command == "p6-closure":
        return p6_closure_main(args[1:])
    print(f"未知 release 命令: {command}. 支持: consumer-acceptance-import, p6-closure", file=sys.stderr)
    return EXIT_BLOCKED


__all__ = [
    "PersistentAuthorizationLedger",
    "consumer_acceptance_import_main",
    "main",
    "p6_closure_main",
]
