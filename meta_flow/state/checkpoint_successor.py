"""历史 checkpoint result 的 canonical append-only successor writer。"""

from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.checks import cp_result
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.state import checkpoint_projection, event_ledger
from meta_flow.state.projection_transaction import (
    atomic_remove_regular_file,
    atomic_replace_bytes,
)

TRANSACTION_REL = Path(".meta-flow-runtime/checkpoint-successor/transaction.json")


def _digest(value: bytes | None) -> str:
    return "missing" if value is None else sha256(value).hexdigest()


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _read_regular(path: Path) -> bytes | None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"checkpoint successor target is not a regular file: {path}")
    return path.read_bytes() if path.is_file() else None


def _replace(path: Path, content: bytes) -> None:
    atomic_replace_bytes(path, content)


def _process_oid(project_root: Path) -> str:
    process = _resolve_runtime_ref(project_root.resolve(), "process/PROJECT.yaml").parent
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=process,
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip().lower()
    if (
        result.returncode != 0
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError("process HEAD must be one lowercase 40-hex OID")
    return value


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    _replace(path, _json_bytes(payload))


def _encode(value: bytes | None) -> str | None:
    return None if value is None else base64.b64encode(value).decode("ascii")


def _decode(value: object) -> bytes | None:
    return None if value is None else base64.b64decode(str(value), validate=True)


@dataclass(frozen=True)
class CheckpointSuccessorPlanV1:
    source_ref: str
    target_ref: str
    process_oid: str
    source_preimage: str
    target_preimage: str
    ledger_preimage: str
    successor: dict[str, Any]
    event: dict[str, Any]
    decision: str
    blockers: tuple[str, ...]
    mutation_count: int
    schema_version: int = 1
    kind: str = "CheckpointSuccessorPlanV1"

    @property
    def plan_digest(self) -> str:
        return canonical_digest(
            {
                "schema_version": self.schema_version,
                "kind": self.kind,
                "source_ref": self.source_ref,
                "target_ref": self.target_ref,
                "process_oid": self.process_oid,
                "source_preimage": self.source_preimage,
                "target_preimage": self.target_preimage,
                "ledger_preimage": self.ledger_preimage,
                "successor": self.successor,
                "event": self.event,
                "decision": self.decision,
                "blockers": list(self.blockers),
                "mutation_count": self.mutation_count,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_ref": self.source_ref,
            "target_ref": self.target_ref,
            "process_oid": self.process_oid,
            "source_preimage": self.source_preimage,
            "target_preimage": self.target_preimage,
            "ledger_preimage": self.ledger_preimage,
            "successor": self.successor,
            "event": self.event,
            "decision": self.decision,
            "blockers": list(self.blockers),
            "mutation_count": self.mutation_count,
            "plan_digest": self.plan_digest,
        }


def _legacy_items(
    source: dict[str, Any], *, evidence_refs: tuple[str, ...]
) -> tuple[list[dict[str, Any]], list[str]]:
    raw_items = source.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raw_items = source.get("checks")
    if not isinstance(raw_items, list) or not raw_items:
        return [], ["SOURCE_ITEMS_UNAVAILABLE"]
    items: list[dict[str, Any]] = []
    blockers: list[str] = []
    for index, raw in enumerate(raw_items, 1):
        if not isinstance(raw, dict):
            blockers.append(f"SOURCE_ITEM_NOT_OBJECT:{index}")
            continue
        status = str(raw.get("status") or "").upper()
        mapped = {
            "PASS": "PASS",
            "FAIL": "FAIL",
            "BLOCKED": "BLOCKED",
            "N/A": "N/A",
            "WAIVED": "WAIVED",
            "FAIL_BASELINE_ONLY": "FAIL",
        }.get(status)
        if mapped is None:
            blockers.append(f"SOURCE_ITEM_STATUS_UNSUPPORTED:{index}:{status or '-'}")
            continue
        refs = raw.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            refs = list(evidence_refs)
        item = {
            "id": str(raw.get("id") or f"LEGACY-{index:02d}"),
            "name": str(raw.get("name") or raw.get("summary") or f"legacy item {index}"),
            "status": mapped,
            "severity": str(raw.get("severity") or "INFO").upper(),
            "evidence_refs": refs,
        }
        if status != mapped:
            item["legacy_status"] = status
        items.append(item)
    return items, blockers


def plan_checkpoint_successor(
    project_root: Path,
    *,
    source_ref: str,
    target_ref: str,
    evidence_refs: tuple[str, ...],
    reason: str,
    process_oid: str | None = None,
) -> CheckpointSuccessorPlanV1:
    """生成零写 successor plan；只接受 current canonical CP0..CP8 head。"""

    root = project_root.resolve()
    blockers: list[str] = []
    if not source_ref.startswith("process/checks/") or not target_ref.startswith("process/checks/"):
        blockers.append("RESULT_REFS_MUST_BE_PROCESS_CHECKS")
    if source_ref == target_ref:
        blockers.append("TARGET_REF_MUST_DIFFER")
    if not evidence_refs or any(not ref.startswith("process/") for ref in evidence_refs):
        blockers.append("EVIDENCE_REFS_MUST_BE_NONEMPTY_PROCESS_REFS")
    if not reason.strip():
        blockers.append("REASON_REQUIRED")
    source_path = _resolve_runtime_ref(root, source_ref)
    target_path = _resolve_runtime_ref(root, target_ref)
    ledger_path = _resolve_runtime_ref(root, checkpoint_projection.CHECKPOINT_LEDGER_REF)
    source_bytes = _read_regular(source_path)
    target_bytes = _read_regular(target_path)
    ledger_bytes = _read_regular(ledger_path)
    source: dict[str, Any] = {}
    if source_bytes is None:
        blockers.append("SOURCE_RESULT_MISSING")
    else:
        try:
            payload = json.loads(source_bytes)
            source = payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            blockers.append("SOURCE_RESULT_INVALID_JSON")
    checkpoint = str(source.get("checkpoint") or source.get("checkpoint_id") or "").upper()
    cr_id = str(source.get("cr_id") or "")
    if not cr_id or not cp_result.CHECKPOINT_RE.fullmatch(checkpoint):
        blockers.append("SOURCE_CHECKPOINT_IDENTITY_INVALID")
    events: list[dict[str, Any]] = []
    if ledger_bytes is None:
        blockers.append("CHECKPOINT_LEDGER_MISSING")
    else:
        events, load_errors = event_ledger.load_events(ledger_path)
        blockers.extend(f"CHECKPOINT_LEDGER_INVALID:{item}" for item in load_errors)
    source_events = [
        event
        for event in events
        if str(event.get("result_ref") or "") == source_ref
        and str(event.get("cr_id") or "") == cr_id
        and str(event.get("checkpoint") or "").upper() == checkpoint
    ]
    if len(source_events) != 1:
        blockers.append("SOURCE_CURRENT_EVENT_NOT_UNIQUE")
    projection = (
        checkpoint_projection.load_checkpoint_projection(
            root,
            cr_id=cr_id,
            checkpoint=checkpoint,
            candidate_refs=(source_ref,),
        )
        if cr_id and checkpoint
        else None
    )
    if projection is not None:
        blockers.extend(
            f"SOURCE_PROJECTION_BLOCKED:{finding.code}" for finding in projection.findings
        )
        if not any(head.result_ref == source_ref for head in projection.heads):
            blockers.append("SOURCE_RESULT_IS_NOT_CURRENT_HEAD")
    items, item_blockers = _legacy_items(source, evidence_refs=evidence_refs)
    blockers.extend(item_blockers)
    parent_event = source_events[0] if len(source_events) == 1 else {}
    revision = int(parent_event.get("revision") or source.get("revision") or 1) + 1
    successor = {
        "schema_version": 1,
        "artifact_kind": "checkpoint_result",
        "checkpoint": checkpoint,
        "cr_id": cr_id,
        "decision": str(source.get("decision") or "").upper(),
        "items": items,
        "blockers": source.get("blockers") if isinstance(source.get("blockers"), list) else [],
        "waivers": source.get("waivers") if isinstance(source.get("waivers"), list) else [],
        "revision": revision,
        "supersedes_ref": source_ref,
        "source_result_digest": _digest(source_bytes),
        "migration_reason": reason,
        "evidence_refs": list(evidence_refs),
    }
    for field in (
        "story_id",
        "context_ref",
        "evidence_ref",
        "dispatch_refs",
        "checker_provenance",
        "checked_at",
    ):
        if source.get(field) not in (None, ""):
            successor[field] = source[field]
    event_seed = {
        "cr_id": cr_id,
        "checkpoint": checkpoint,
        "result_ref": target_ref,
        "revision": revision,
        "source_result_digest": _digest(source_bytes),
    }
    event_id = f"CP-SUCCESSOR-{canonical_digest(event_seed)[:32]}"
    event = {
        "event_id": event_id,
        "event_type": "checkpoint_result",
        "checkpoint": checkpoint,
        "cr_id": cr_id,
        "decision": successor["decision"],
        "result_ref": target_ref,
        "revision": revision,
        "supersedes_event_id": str(parent_event.get("event_id") or ""),
        "supersedes_ref": source_ref,
    }
    if successor.get("story_id"):
        event["story_id"] = successor["story_id"]
    if target_bytes is not None:
        if target_bytes == _json_bytes(successor) and event_id in {
            str(item.get("event_id") or "") for item in events
        }:
            # 精确 successor 已提交后，source 按定义不再是 current head。
            # 该 finding 是幂等回放的预期后像，不得与 NO_CHANGE 同时作为 blocker 返回。
            blockers = [item for item in blockers if item != "SOURCE_RESULT_IS_NOT_CURRENT_HEAD"]
            decision = "BLOCKED" if blockers else "NO_CHANGE"
            mutation_count = 0
        else:
            blockers.append("TARGET_ALREADY_EXISTS")
            decision, mutation_count = "BLOCKED", 0
    elif blockers:
        decision, mutation_count = "BLOCKED", 0
    else:
        decision, mutation_count = "READY", 2
    return CheckpointSuccessorPlanV1(
        source_ref=source_ref,
        target_ref=target_ref,
        process_oid=process_oid or _process_oid(root),
        source_preimage=_digest(source_bytes),
        target_preimage=_digest(target_bytes),
        ledger_preimage=_digest(ledger_bytes),
        successor=successor,
        event=event,
        decision=decision,
        blockers=tuple(sorted(set(blockers))),
        mutation_count=mutation_count,
    )


def apply_checkpoint_successor(
    project_root: Path,
    *,
    plan: CheckpointSuccessorPlanV1,
    expected_plan_digest: str,
    expected_process_oid: str | None = None,
    current_process_oid: str | None = None,
) -> dict[str, Any]:
    """在 source/target/ledger preimage 全部匹配时提交 result+ledger。"""

    root = project_root.resolve()
    if expected_plan_digest != plan.plan_digest:
        return {"decision": "BLOCKED", "blockers": ["PLAN_DIGEST_MISMATCH"], "mutation_count": 0}
    if plan.decision == "NO_CHANGE":
        return {"decision": "NO_CHANGE", "blockers": [], "mutation_count": 0}
    if plan.decision != "READY":
        return {"decision": "BLOCKED", "blockers": list(plan.blockers), "mutation_count": 0}
    actual_process_oid = current_process_oid or _process_oid(root)
    if expected_process_oid is not None and expected_process_oid != plan.process_oid:
        return {
            "decision": "BLOCKED",
            "blockers": ["PROCESS_OID_EXPECTATION_MISMATCH"],
            "mutation_count": 0,
        }
    if actual_process_oid != plan.process_oid:
        return {"decision": "BLOCKED", "blockers": ["PROCESS_OID_DRIFT"], "mutation_count": 0}
    source_path = _resolve_runtime_ref(root, plan.source_ref)
    target_path = _resolve_runtime_ref(root, plan.target_ref)
    ledger_path = _resolve_runtime_ref(root, checkpoint_projection.CHECKPOINT_LEDGER_REF)
    current = (
        _digest(_read_regular(source_path)),
        _digest(_read_regular(target_path)),
        _digest(_read_regular(ledger_path)),
    )
    expected = (plan.source_preimage, plan.target_preimage, plan.ledger_preimage)
    if current != expected:
        return {
            "decision": "BLOCKED",
            "blockers": ["SOURCE_OR_LEDGER_PREIMAGE_DRIFT"],
            "mutation_count": 0,
        }
    result_bytes = _json_bytes(plan.successor)
    ledger_before = _read_regular(ledger_path) or b""
    if ledger_before and not ledger_before.endswith(b"\n"):
        ledger_before += b"\n"
    ledger_after = ledger_before + (
        json.dumps(plan.event, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    manifest_path = root / TRANSACTION_REL
    inspection = inspect_checkpoint_successor(root)
    if inspection["decision"] == "BLOCKED":
        return {"decision": "BLOCKED", "blockers": ["RECOVERY_REQUIRED"], "mutation_count": 0}
    manifest = {
        "schema_version": 1,
        "kind": "CheckpointSuccessorTransactionV1",
        "state": "PREPARED",
        "plan_digest": plan.plan_digest,
        "target_ref": plan.target_ref,
        "ledger_ref": checkpoint_projection.CHECKPOINT_LEDGER_REF,
        "target_before": _encode(_read_regular(target_path)),
        "ledger_before": _encode(ledger_before),
        "target_after_digest": _digest(result_bytes),
        "ledger_after_digest": _digest(ledger_after),
        "attempted_refs": [],
    }
    _write_manifest(manifest_path, manifest)
    manifest["state"] = "APPLYING"
    _write_manifest(manifest_path, manifest)
    try:
        _replace(target_path, result_bytes)
        manifest["attempted_refs"].append(plan.target_ref)
        _write_manifest(manifest_path, manifest)
        _replace(ledger_path, ledger_after)
        manifest["attempted_refs"].append(checkpoint_projection.CHECKPOINT_LEDGER_REF)
        manifest["state"] = "COMMITTED"
        _write_manifest(manifest_path, manifest)
    except Exception as exc:
        manifest["state"] = "PARTIAL"
        manifest["failure"] = str(exc)
        _write_manifest(manifest_path, manifest)
        return {
            "decision": "BLOCKED",
            "blockers": ["RECOVERY_REQUIRED"],
            "mutation_count": len(manifest["attempted_refs"]),
        }
    return {
        "schema_version": 1,
        "kind": "CheckpointSuccessorReceiptV1",
        "decision": "APPLIED",
        "source_ref": plan.source_ref,
        "target_ref": plan.target_ref,
        "event_id": plan.event["event_id"],
        "plan_digest": plan.plan_digest,
        "mutation_count": 2,
    }


def inspect_checkpoint_successor(project_root: Path) -> dict[str, Any]:
    """检查 durable successor transaction；不修改任何文件。"""

    root = project_root.resolve()
    path = root / TRANSACTION_REL
    if not path.is_file():
        return {"decision": "PASS", "state": "NONE", "findings": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"decision": "BLOCKED", "state": "INVALID", "findings": [str(exc)]}
    if not isinstance(payload, dict) or payload.get("kind") != "CheckpointSuccessorTransactionV1":
        return {
            "decision": "BLOCKED",
            "state": "INVALID",
            "findings": ["transaction manifest invalid"],
        }
    state = str(payload.get("state") or "")
    target = _resolve_runtime_ref(root, str(payload.get("target_ref") or ""))
    ledger = _resolve_runtime_ref(root, str(payload.get("ledger_ref") or ""))
    current = (_digest(_read_regular(target)), _digest(_read_regular(ledger)))
    if state == "COMMITTED":
        expected = (
            str(payload.get("target_after_digest") or ""),
            str(payload.get("ledger_after_digest") or ""),
        )
        findings = [] if current == expected else ["committed target digest mismatch"]
        return {
            "decision": "PASS" if not findings else "BLOCKED",
            "state": state,
            "findings": findings,
        }
    if state == "RECOVERED":
        expected = (
            _digest(_decode(payload.get("target_before"))),
            _digest(_decode(payload.get("ledger_before"))),
        )
        findings = [] if current == expected else ["recovered target digest mismatch"]
        return {
            "decision": "PASS" if not findings else "BLOCKED",
            "state": state,
            "findings": findings,
        }
    return {"decision": "BLOCKED", "state": state or "INVALID", "findings": ["recovery required"]}


def recover_checkpoint_successor(project_root: Path) -> dict[str, Any]:
    """将 PREPARED/APPLYING/PARTIAL transaction 恢复到冻结 preimage。"""

    root = project_root.resolve()
    path = root / TRANSACTION_REL
    inspection = inspect_checkpoint_successor(root)
    if inspection["state"] in {"NONE", "COMMITTED", "RECOVERED"}:
        return {"decision": "NO_CHANGE", "state": inspection["state"], "mutation_count": 0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    target = _resolve_runtime_ref(root, str(payload["target_ref"]))
    ledger = _resolve_runtime_ref(root, str(payload["ledger_ref"]))
    target_before = _decode(payload.get("target_before"))
    ledger_before = _decode(payload.get("ledger_before"))
    if target_before is None:
        atomic_remove_regular_file(target)
    else:
        _replace(target, target_before)
    if ledger_before is None:
        atomic_remove_regular_file(ledger)
    else:
        _replace(ledger, ledger_before)
    payload["state"] = "RECOVERED"
    _write_manifest(path, payload)
    return {"decision": "RECOVERED", "state": "RECOVERED", "mutation_count": 2}


__all__ = [
    "CheckpointSuccessorPlanV1",
    "apply_checkpoint_successor",
    "inspect_checkpoint_successor",
    "plan_checkpoint_successor",
    "recover_checkpoint_successor",
]
