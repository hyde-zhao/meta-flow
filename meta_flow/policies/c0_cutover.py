"""C0 first-activation cutover 的冻结计划、授权与事务执行。

V2 把五个 durable target 的 before/after、checkpoint/gate history 与 writer
边界全部冻结在授权之前。该模块不判断 bootstrap 语义；它只消费已经 READY 的
semantic dry-run，并负责 write-side 安全。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.checks import state_transition
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import ProcessRouteError, _resolve_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.state import checkpoint_projection, event_ledger

C0_CUTOVER_OPERATION = "route-c0-cutover-apply"
C0_AUTHORIZATION_SOURCE = "typed-user-confirmation"
C0_AUTHORIZATION_KIND = "c0-cutover-v2"
C0_WRITE_OWNER = "meta_flow.policies.c0_cutover:C0CutoverPlanV2"
C0_PLAN_KIND = "C0CutoverPlanV2"
C0_RESULT_KIND = "C0ApplyResultV2"
C0_TARGET_COUNT = 5
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_AUTHORIZATION_FIELDS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "authorization_source",
        "authorization_kind",
        "operation",
        "cr_id",
        "work_id",
        "expected_release_oid",
        "expected_process_oid",
        "scope_digest",
        "process_dirty_path_digest",
        "plan_digest",
        "mutation_allowlist",
        "expires_at",
        "single_use",
    }
)


def _now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _optional_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _append_ndjson(before: str | None, event: Mapping[str, Any]) -> str:
    prefix = before or ""
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    payload = {key: value for key, value in event.items() if key != "_line_no"}
    return prefix + json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"


def _git_value(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise ValueError(f"git {' '.join(args)} failed")
    return value


def _dirty_path_digest(root: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError("cannot query process dirty paths")
    entries = [
        entry.decode("utf-8", errors="surrogateescape")
        for entry in result.stdout.split(b"\0")
        if entry
    ]
    return canonical_digest(sorted(entries))


def _git_common_dir(root: Path) -> Path:
    raw = _git_value(root, "rev-parse", "--git-common-dir")
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class C0CutoverTargetV2:
    """一个已冻结的 process mutation target。"""

    order: int
    logical_ref: str
    path: Path
    before: str | None
    after: str

    @property
    def before_digest(self) -> str:
        return canonical_digest(self.before if self.before is not None else "")

    @property
    def after_digest(self) -> str:
        return canonical_digest(self.after)

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "logical_ref": self.logical_ref,
            "carry_mode": "replace" if self.before is not None else "create",
            "before_exists": self.before is not None,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
        }


@dataclass(frozen=True)
class C0CutoverPlanV2:
    """授权前可稳定重放的 C0 write-side plan。"""

    cr_id: str
    work_id: str
    release_oid: str
    process_oid: str
    scope_digest: str
    process_dirty_path_digest: str
    semantic_plan_digest: str
    checkpoint_history_digest: str
    gate_history_digest: str
    checkpoint_history_count: int
    gate_history_count: int
    cutover_intent_digest: str
    targets: tuple[C0CutoverTargetV2, ...]
    blockers: tuple[str, ...]
    decision: str

    @property
    def mutation_allowlist(self) -> tuple[str, ...]:
        return tuple(target.logical_ref for target in self.targets)

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "kind": C0_PLAN_KIND,
            "operation": C0_CUTOVER_OPERATION,
            "decision": self.decision,
            "dry_run": True,
            "actual_mutation_count": 0,
            "planned_mutation_count": len(self.targets),
            "cr_id": self.cr_id,
            "work_id": self.work_id,
            "release_oid": self.release_oid,
            "process_oid": self.process_oid,
            "scope_digest": self.scope_digest,
            "process_dirty_path_digest": self.process_dirty_path_digest,
            "semantic_plan_digest": self.semantic_plan_digest,
            "checkpoint_history_digest": self.checkpoint_history_digest,
            "gate_history_digest": self.gate_history_digest,
            "checkpoint_history_count": self.checkpoint_history_count,
            "gate_history_count": self.gate_history_count,
            "activation_mode": "first-activation-only",
            "cutover_intent_digest": self.cutover_intent_digest,
            "mutation_allowlist": list(self.mutation_allowlist),
            "targets": [target.as_dict() for target in self.targets],
            "rollback_order": list(reversed(self.mutation_allowlist)),
            "blockers": list(self.blockers),
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["plan_digest"] = canonical_digest(payload)
        return payload


@dataclass(frozen=True)
class C0CutoverAuthorizationV2:
    schema_version: int
    authorization_id: str
    authorization_source: str
    authorization_kind: str
    operation: str
    cr_id: str
    work_id: str
    expected_release_oid: str
    expected_process_oid: str
    scope_digest: str
    process_dirty_path_digest: str
    plan_digest: str
    mutation_allowlist: tuple[str, ...]
    expires_at: str
    single_use: bool

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> C0CutoverAuthorizationV2:
        if set(payload) != _AUTHORIZATION_FIELDS:
            missing = sorted(_AUTHORIZATION_FIELDS - set(payload))
            extra = sorted(set(payload) - _AUTHORIZATION_FIELDS)
            raise ValueError(
                f"C0 V2 authorization fields mismatch: missing={missing}, extra={extra}"
            )
        allowlist = payload.get("mutation_allowlist")
        if not isinstance(allowlist, list):
            raise ValueError("C0 V2 authorization mutation_allowlist must be a list")
        return cls(
            schema_version=int(payload["schema_version"]),
            authorization_id=str(payload["authorization_id"]),
            authorization_source=str(payload["authorization_source"]),
            authorization_kind=str(payload["authorization_kind"]),
            operation=str(payload["operation"]),
            cr_id=str(payload["cr_id"]),
            work_id=str(payload["work_id"]),
            expected_release_oid=str(payload["expected_release_oid"]),
            expected_process_oid=str(payload["expected_process_oid"]),
            scope_digest=str(payload["scope_digest"]),
            process_dirty_path_digest=str(payload["process_dirty_path_digest"]),
            plan_digest=str(payload["plan_digest"]),
            mutation_allowlist=tuple(str(item) for item in allowlist),
            expires_at=str(payload["expires_at"]),
            single_use=payload["single_use"] is True,
        )


def _semantic_payload(semantic_plan: Any) -> dict[str, Any]:
    payload = semantic_plan.as_dict()
    if not isinstance(payload, dict):
        raise ValueError("C0 semantic plan must produce an object")
    return payload


def _target_history(
    path: Path,
    *,
    ledger_type: str,
    cr_id: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    events, errors = event_ledger.load_events(path)
    if not path.is_file():
        return [], []
    if errors:
        return [], [f"{ledger_type.upper()}_LEDGER_INVALID:{error}" for error in errors]
    if ledger_type == "checkpoint":
        target = [
            event
            for event in events
            if str(event.get("event_type") or "") == "checkpoint_result"
            and str(event.get("checkpoint") or "") == "C0"
            and str(event.get("cr_id") or "") == cr_id
        ]
    else:
        target = [
            event
            for event in events
            if str(event.get("event_type") or "") == "gate_passed"
            and str(event.get("gate") or "") == f"CUTOVER-GATE-{cr_id}-C0"
            and str(event.get("cr_id") or "") == cr_id
        ]
    return [
        {key: value for key, value in event.items() if key != "_line_no"} for event in target
    ], []


def build_c0_cutover_plan(
    *,
    project_root: Path,
    work_id: str,
    semantic_plan: Any,
) -> C0CutoverPlanV2:
    """冻结 first-activation 的五目标计划，永远不修改 process。"""

    root = project_root.resolve()
    semantic = _semantic_payload(semantic_plan)
    cr_id = str(semantic.get("cr_id") or "")
    release_oid = str(semantic.get("release_oid") or "")
    process_oid = str(semantic.get("process_oid") or "")
    scope_digest = str(semantic.get("scope_digest") or "")
    semantic_plan_digest = str(semantic.get("plan_digest") or "")
    blockers: list[str] = []
    if semantic.get("decision") != "READY":
        blockers.append("C0_SEMANTIC_PLAN_NOT_READY")
    if semantic.get("dry_run") is not True or semantic.get("mutation_count") != 0:
        blockers.append("C0_SEMANTIC_PLAN_NOT_ZERO_MUTATION")
    expected_allowlist = (
        "process/DEVELOPMENT-PLAN.yaml",
        f"process/checks/C0-{cr_id}-PROJECTOR-CUTOVER.result.json",
        f"process/checks/C0-{cr_id}-PROJECTOR-CUTOVER.summary.md",
        "process/state/CHECKPOINT-LEDGER.ndjson",
        "process/state/GATE-LEDGER.ndjson",
    )
    if tuple(str(item) for item in semantic.get("mutation_allowlist") or ()) != (
        expected_allowlist
    ):
        blockers.append("C0_SEMANTIC_MUTATION_ALLOWLIST_MISMATCH")

    process_project = _resolve_runtime_ref(root, "process/PROJECT.yaml")
    process_root = process_project.parent
    observed_release_oid = _git_value(root, "rev-parse", "HEAD")
    observed_process_oid = _git_value(process_root, "rev-parse", "HEAD")
    if observed_release_oid != release_oid:
        blockers.append("C0_RELEASE_OID_DRIFT")
    if observed_process_oid != process_oid:
        blockers.append("C0_PROCESS_OID_DRIFT")
    process_dirty_path_digest = _dirty_path_digest(process_root)

    development_plan_path = _resolve_runtime_ref(
        root,
        "process/DEVELOPMENT-PLAN.yaml",
    )
    result_ref = expected_allowlist[1]
    summary_ref = expected_allowlist[2]
    checkpoint_ledger_ref = expected_allowlist[3]
    gate_ledger_ref = expected_allowlist[4]
    result_path = _resolve_runtime_ref(root, result_ref)
    summary_path = _resolve_runtime_ref(root, summary_ref)
    checkpoint_ledger_path = _resolve_runtime_ref(root, checkpoint_ledger_ref)
    gate_ledger_path = _resolve_runtime_ref(root, gate_ledger_ref)

    checkpoint_history, checkpoint_errors = _target_history(
        checkpoint_ledger_path,
        ledger_type="checkpoint",
        cr_id=cr_id,
    )
    gate_history, gate_errors = _target_history(
        gate_ledger_path,
        ledger_type="gate",
        cr_id=cr_id,
    )
    blockers.extend(checkpoint_errors)
    blockers.extend(gate_errors)
    if checkpoint_history or gate_history:
        blockers.append("C0_V2_FIRST_ACTIVATION_HISTORY_MUST_BE_EMPTY")
    if len(checkpoint_history) != len(gate_history):
        blockers.append("C0_CHECKPOINT_GATE_HISTORY_INCONSISTENT")
    checkpoint_history_digest = canonical_digest(checkpoint_history)
    gate_history_digest = canonical_digest(gate_history)

    before_values = {
        expected_allowlist[0]: _optional_text(development_plan_path),
        result_ref: _optional_text(result_path),
        summary_ref: _optional_text(summary_path),
        checkpoint_ledger_ref: _optional_text(checkpoint_ledger_path),
        gate_ledger_ref: _optional_text(gate_ledger_path),
    }
    before_digests = {
        ref: canonical_digest(value if value is not None else "")
        for ref, value in before_values.items()
    }
    intent_seed = {
        "schema_version": 2,
        "operation": C0_CUTOVER_OPERATION,
        "activation_mode": "first-activation-only",
        "cr_id": cr_id,
        "work_id": work_id,
        "release_oid": release_oid,
        "process_oid": process_oid,
        "scope_digest": scope_digest,
        "process_dirty_path_digest": process_dirty_path_digest,
        "semantic_plan_digest": semantic_plan_digest,
        "checkpoint_history_digest": checkpoint_history_digest,
        "gate_history_digest": gate_history_digest,
        "mutation_allowlist": list(expected_allowlist),
        "before_digests": before_digests,
    }
    cutover_intent_digest = canonical_digest(intent_seed)

    targets: tuple[C0CutoverTargetV2, ...] = ()
    if not blockers:
        try:
            development_plan = load_yaml_object(development_plan_path)
            projected_plan, story_transitions = state_transition.project_c0_development_plan(
                development_plan,
                cr_id=cr_id,
            )
        except (OSError, ValueError) as exc:
            blockers.append(f"C0_DEVELOPMENT_PLAN_PROJECTION_BLOCKED:{exc}")
        else:
            checkpoint_event_id = f"C0-CUTOVER-{cr_id}-{cutover_intent_digest[:24]}"
            gate_event_id = f"GATE-C0-{cr_id}-{cutover_intent_digest[:24]}"
            checkpoint_event = {
                "event_id": checkpoint_event_id,
                "event_type": "checkpoint_result",
                "checkpoint": "C0",
                "decision": "PASS",
                "result_ref": result_ref,
                "cr_id": cr_id,
                "work_id": work_id,
                "cutover_revision": 1,
                "cutover_intent_digest": cutover_intent_digest,
                "semantic_plan_digest": semantic_plan_digest,
            }
            gate_event = {
                "event_id": gate_event_id,
                "event_type": "gate_passed",
                "gate": f"CUTOVER-GATE-{cr_id}-C0",
                "status": "passed",
                "decision": "PASS",
                "result_ref": result_ref,
                "cr_id": cr_id,
                "work_id": work_id,
                "cutover_revision": 1,
                "cutover_intent_digest": cutover_intent_digest,
                "semantic_plan_digest": semantic_plan_digest,
            }
            try:
                event_ledger.validate_event_before_append(
                    checkpoint_ledger_path,
                    checkpoint_event,
                    ledger_type="checkpoint",
                )
                event_ledger.validate_event_before_append(
                    gate_ledger_path,
                    gate_event,
                    ledger_type="gate",
                )
            except ValueError as exc:
                blockers.append(f"C0_EVENT_VALIDATION_BLOCKED:{exc}")
            result_payload = {
                "schema_version": 2,
                "kind": C0_RESULT_KIND,
                "checkpoint": "C0",
                "cr_id": cr_id,
                "work_id": work_id,
                "decision": "PASS",
                "status": "passed",
                "release_oid": release_oid,
                "process_oid": process_oid,
                "scope_digest": scope_digest,
                "semantic_plan_digest": semantic_plan_digest,
                "cutover_intent_digest": cutover_intent_digest,
                "cutover_revision": 1,
                "checkpoint_event_id": checkpoint_event_id,
                "gate_event_id": gate_event_id,
                "story_transitions": list(story_transitions),
                "mutation_allowlist": list(expected_allowlist),
            }
            simulated_projection = checkpoint_projection.project_checkpoint_events(
                [checkpoint_event],
                {result_ref: result_payload},
                cr_id=cr_id,
                checkpoint="C0",
            )
            simulated_head = simulated_projection.head("C0")
            if (
                simulated_projection.findings
                or simulated_head is None
                or simulated_head.event_id != checkpoint_event_id
                or simulated_head.result_ref != result_ref
            ):
                blockers.append("C0_CANONICAL_PROJECTION_CONFORMANCE_BLOCKED")
            result_after = (
                json.dumps(
                    result_payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            summary_after = (
                f"# C0 {cr_id} First-Activation Cutover\n\n"
                f"- decision：`PASS`\n"
                f"- activation mode：`first-activation-only`\n"
                f"- cutover intent digest：`{cutover_intent_digest}`\n"
                f"- semantic plan digest：`{semantic_plan_digest}`\n"
                f"- checkpoint event：`{checkpoint_event_id}`\n"
                f"- gate event：`{gate_event_id}`\n"
            )
            target_values = (
                (
                    expected_allowlist[0],
                    development_plan_path,
                    json.dumps(
                        projected_plan,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                ),
                (result_ref, result_path, result_after),
                (summary_ref, summary_path, summary_after),
                (
                    checkpoint_ledger_ref,
                    checkpoint_ledger_path,
                    _append_ndjson(
                        before_values[checkpoint_ledger_ref],
                        checkpoint_event,
                    ),
                ),
                (
                    gate_ledger_ref,
                    gate_ledger_path,
                    _append_ndjson(
                        before_values[gate_ledger_ref],
                        gate_event,
                    ),
                ),
            )
            targets = tuple(
                C0CutoverTargetV2(
                    order=index,
                    logical_ref=logical_ref,
                    path=path,
                    before=before_values[logical_ref],
                    after=after,
                )
                for index, (logical_ref, path, after) in enumerate(
                    target_values,
                    1,
                )
            )
    if blockers:
        targets = ()
    return C0CutoverPlanV2(
        cr_id=cr_id,
        work_id=work_id,
        release_oid=release_oid,
        process_oid=process_oid,
        scope_digest=scope_digest,
        process_dirty_path_digest=process_dirty_path_digest,
        semantic_plan_digest=semantic_plan_digest,
        checkpoint_history_digest=checkpoint_history_digest,
        gate_history_digest=gate_history_digest,
        checkpoint_history_count=len(checkpoint_history),
        gate_history_count=len(gate_history),
        cutover_intent_digest=cutover_intent_digest,
        targets=targets,
        blockers=tuple(sorted(set(blockers))),
        decision="READY" if not blockers else "BLOCKED",
    )


def validate_c0_cutover_authorization(
    plan: C0CutoverPlanV2,
    authorization: C0CutoverAuthorizationV2,
) -> None:
    """验证 typed authorization 与完整 V2 plan 的精确绑定。"""

    if plan.decision != "READY":
        raise ValueError("C0 V2 authorization requires READY plan")
    if authorization.schema_version != 2:
        raise ValueError("C0 V2 authorization schema_version must be 2")
    if not _AUTH_ID_RE.fullmatch(authorization.authorization_id):
        raise ValueError("C0 V2 authorization_id is invalid")
    if authorization.authorization_source != C0_AUTHORIZATION_SOURCE:
        raise ValueError("C0 V2 authorization_source mismatch")
    if authorization.authorization_kind != C0_AUTHORIZATION_KIND:
        raise ValueError("C0 V2 authorization_kind mismatch")
    if authorization.operation != C0_CUTOVER_OPERATION:
        raise ValueError("C0 V2 authorization operation mismatch")
    if authorization.single_use is not True:
        raise ValueError("C0 V2 authorization must be single-use")
    expected = (
        plan.cr_id,
        plan.work_id,
        plan.release_oid,
        plan.process_oid,
        plan.scope_digest,
        plan.process_dirty_path_digest,
        plan.as_dict()["plan_digest"],
        plan.mutation_allowlist,
    )
    actual = (
        authorization.cr_id,
        authorization.work_id,
        authorization.expected_release_oid,
        authorization.expected_process_oid,
        authorization.scope_digest,
        authorization.process_dirty_path_digest,
        authorization.plan_digest,
        authorization.mutation_allowlist,
    )
    if actual != expected:
        raise ValueError("C0 V2 authorization does not match frozen plan")
    if not _OID_RE.fullmatch(authorization.expected_release_oid) or not _OID_RE.fullmatch(
        authorization.expected_process_oid
    ):
        raise ValueError("C0 V2 authorization OID is invalid")
    for digest in (
        authorization.scope_digest,
        authorization.process_dirty_path_digest,
        authorization.plan_digest,
    ):
        if not _DIGEST_RE.fullmatch(digest):
            raise ValueError("C0 V2 authorization digest is invalid")
    try:
        expires_at = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("C0 V2 authorization expires_at is invalid") from exc
    if expires_at.tzinfo is None or expires_at.astimezone(UTC) <= datetime.now(UTC):
        raise ValueError("C0 V2 authorization is expired")


def _private_root(release_root: Path) -> Path:
    return _git_common_dir(release_root) / "meta-flow" / "c0-cutover-v2"


def _receipt_path(release_root: Path, plan_digest: str) -> Path:
    return _private_root(release_root) / "receipts" / f"{plan_digest}.json"


def _authorization_claim_path(
    release_root: Path,
    authorization_id: str,
) -> Path:
    claim_name = canonical_digest({"authorization_id": authorization_id})
    return _private_root(release_root) / "authorizations" / f"{claim_name}.json"


def _verify_receipt_no_change(
    release_root: Path,
    plan_digest: str,
) -> dict[str, Any] | None:
    path = _receipt_path(release_root, plan_digest)
    if not path.is_file():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(receipt, dict) or receipt.get("plan_digest") != plan_digest:
        return None
    targets = receipt.get("targets")
    if not isinstance(targets, list):
        return None
    for target in targets:
        if not isinstance(target, dict):
            return None
        logical_ref = str(target.get("logical_ref") or "")
        current_path = _resolve_runtime_ref(release_root, logical_ref)
        current = _optional_text(current_path)
        if canonical_digest(current if current is not None else "") != str(
            target.get("after_digest") or ""
        ):
            return None
    return {
        "status": "NO_CHANGE",
        "decision": "PASS",
        "plan_digest": plan_digest,
        "mutation_count": 0,
        "path_refs": [],
        "receipt_ref": f"private://c0-cutover-v2/receipts/{path.name}",
    }


def apply_c0_cutover(
    *,
    project_root: Path,
    work_id: str,
    expected_plan_digest: str,
    authorization: C0CutoverAuthorizationV2 | None,
    semantic_plan_factory: Callable[[], Any],
    _fail_after_replace: int | None = None,
    _rollback_failure_ref: str = "",
    _fail_before_receipt: bool = False,
) -> dict[str, Any]:
    """重建 byte-identical plan 后执行五目标事务；失败时逆序精确恢复。"""

    release_root = project_root.resolve()
    no_change = _verify_receipt_no_change(release_root, expected_plan_digest)
    if no_change is not None:
        return no_change
    process_root: Path | None = None
    lock_path: Path | None = None
    transaction_dir: Path | None = None
    try:
        semantic_plan = semantic_plan_factory()
        plan = build_c0_cutover_plan(
            project_root=release_root,
            work_id=work_id,
            semantic_plan=semantic_plan,
        )
        plan_digest = plan.as_dict()["plan_digest"]
        if plan.decision != "READY":
            return {
                "status": "BLOCKED",
                "decision": plan.decision,
                "blockers": list(plan.blockers),
                "mutation_count": 0,
            }
        if not expected_plan_digest or expected_plan_digest != plan_digest:
            return {
                "status": "BLOCKED",
                "reason": "expected C0 V2 plan digest does not match dry-run",
                "mutation_count": 0,
            }
        if authorization is None:
            return {
                "status": "BLOCKED",
                "reason": "C0 V2 apply requires typed authorization",
                "mutation_count": 0,
            }
        validate_c0_cutover_authorization(plan, authorization)

        process_project = _resolve_runtime_ref(release_root, "process/PROJECT.yaml")
        process_root = process_project.parent
        private_root = _private_root(release_root)
        transaction_root = private_root / "transactions"
        transaction_root.mkdir(parents=True, exist_ok=True)
        unresolved = sorted(transaction_root.glob("*/manifest.json"))
        if unresolved:
            return {
                "status": "BLOCKED",
                "reason": "unresolved C0 V2 transaction exists",
                "mutation_count": 0,
                "recovery_refs": [
                    f"private://c0-cutover-v2/transactions/{item.parent.name}/manifest.json"
                    for item in unresolved
                ],
            }
        lock_path = _git_common_dir(process_root) / "meta-flow" / "c0-cutover-v2.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with lock_path.open("x", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "operation": C0_CUTOVER_OPERATION,
                            "plan_digest": plan_digest,
                            "created_at": _now_utc(),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
        except FileExistsError:
            return {
                "status": "BLOCKED",
                "reason": "C0 V2 process writer lock exists",
                "mutation_count": 0,
            }

        # 获取 writer lock 后必须从公共 semantic producer 重新生成，并比较完整
        # plan payload（含 preimage/after/allowlist/history/dirty path）。
        fresh = build_c0_cutover_plan(
            project_root=release_root,
            work_id=work_id,
            semantic_plan=semantic_plan_factory(),
        )
        if fresh.as_dict() != plan.as_dict():
            return {
                "status": "BLOCKED",
                "reason": "C0 V2 plan drifted after writer lock",
                "mutation_count": 0,
            }
        drifted = [
            target.logical_ref
            for target in plan.targets
            if canonical_digest(
                _optional_text(target.path) if _optional_text(target.path) is not None else ""
            )
            != target.before_digest
        ]
        if drifted:
            return {
                "status": "BLOCKED",
                "reason": "C0 V2 target preimage drift: " + ", ".join(drifted),
                "mutation_count": 0,
            }

        claim_path = _authorization_claim_path(
            release_root,
            authorization.authorization_id,
        )
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with claim_path.open("x", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "authorization_id": authorization.authorization_id,
                            "plan_digest": plan_digest,
                            "claimed_at": _now_utc(),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
        except FileExistsError:
            return {
                "status": "BLOCKED",
                "reason": "C0 V2 authorization already consumed",
                "mutation_count": 0,
            }

        transaction_id = uuid.uuid4().hex
        transaction_dir = transaction_root / transaction_id
        backup_root = transaction_dir / "backups"
        after_root = transaction_dir / "after"
        backup_root.mkdir(parents=True)
        after_root.mkdir(parents=True)
        manifest_path = transaction_dir / "manifest.json"
        manifest: dict[str, Any] = {
            "schema_version": 2,
            "transaction_id": transaction_id,
            "operation": C0_CUTOVER_OPERATION,
            "cr_id": plan.cr_id,
            "work_id": plan.work_id,
            "plan_digest": plan_digest,
            "authorization_id": authorization.authorization_id,
            "targets": [],
            "durable_leaf_refs": [],
            "recovery_state": "prepared",
            "created_at": _now_utc(),
            "updated_at": _now_utc(),
        }
        for target in plan.targets:
            backup = backup_root / f"{target.order:03d}.before"
            prepared_after = after_root / f"{target.order:03d}.after"
            backup.write_text(target.before or "", encoding="utf-8")
            prepared_after.write_text(target.after, encoding="utf-8")
            manifest["targets"].append(
                {
                    **target.as_dict(),
                    "apply_status": "prepared",
                    "rollback_status": "not-required",
                }
            )
        _atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

        applied: list[C0CutoverTargetV2] = []
        try:
            manifest["recovery_state"] = "applying"
            for offset, target in enumerate(plan.targets, 1):
                current = _optional_text(target.path)
                if canonical_digest(current if current is not None else "") != (
                    target.before_digest
                ):
                    raise RuntimeError(f"C0 V2 target changed during apply: {target.logical_ref}")
                _atomic_write(target.path, target.after)
                applied.append(target)
                manifest["targets"][offset - 1]["apply_status"] = "applied"
                manifest["durable_leaf_refs"] = [item.logical_ref for item in applied]
                manifest["updated_at"] = _now_utc()
                _atomic_write(
                    manifest_path,
                    json.dumps(
                        manifest,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                )
                if _fail_after_replace == offset:
                    raise RuntimeError(f"injected C0 V2 failure after replace {offset}")
            mismatched = [
                target.logical_ref
                for target in plan.targets
                if canonical_digest(_optional_text(target.path) or "") != target.after_digest
            ]
            if mismatched:
                raise RuntimeError("C0 V2 read-back mismatch: " + ", ".join(mismatched))
        except Exception as exc:
            rollback_errors: list[str] = []
            for target in reversed(applied):
                try:
                    if target.logical_ref == _rollback_failure_ref:
                        raise RuntimeError("injected rollback failure")
                    if target.before is None:
                        target.path.unlink(missing_ok=True)
                    else:
                        _atomic_write(target.path, target.before)
                    current = _optional_text(target.path)
                    if canonical_digest(current if current is not None else "") != (
                        target.before_digest
                    ):
                        raise RuntimeError("rollback digest mismatch")
                    for entry in manifest["targets"]:
                        if entry["logical_ref"] == target.logical_ref:
                            entry["rollback_status"] = "restored"
                except Exception as rollback_exc:
                    rollback_errors.append(f"{target.logical_ref}: {rollback_exc}")
            durable_refs = [
                target.logical_ref
                for target in plan.targets
                if canonical_digest(_optional_text(target.path) or "") == target.after_digest
            ]
            status = "PARTIAL" if rollback_errors else "RECOVERED"
            manifest["recovery_state"] = status.lower()
            manifest["durable_leaf_refs"] = durable_refs
            manifest["updated_at"] = _now_utc()
            _atomic_write(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
            if status == "RECOVERED":
                shutil.rmtree(transaction_dir)
            result = {
                "status": status,
                "reason": str(exc),
                "transaction_id": transaction_id,
                "authorization_id": authorization.authorization_id,
                "plan_digest": plan_digest,
                "mutation_count": len(applied),
                "rollback_errors": rollback_errors,
                "durable_leaf_refs": durable_refs,
            }
            if status == "PARTIAL":
                result["recovery_contract"] = {
                    "receipt_ref": (
                        f"private://c0-cutover-v2/transactions/{transaction_id}/manifest.json"
                    ),
                    "required_precondition": (
                        "停止所有 process writer，按 reverse rollback_order "
                        "恢复 before_digest 后重新生成全新 plan/authorization"
                    ),
                    "retry_allowed_after": "all target before_digest restored",
                }
            return result

        receipt_path = _receipt_path(release_root, plan_digest)
        try:
            manifest["recovery_state"] = "committed"
            manifest["updated_at"] = _now_utc()
            _atomic_write(
                manifest_path,
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            if _fail_before_receipt:
                raise RuntimeError("injected C0 V2 receipt persistence failure")
            receipt = {
                "schema_version": 2,
                "kind": "C0CutoverReceiptV2",
                "status": "PASS",
                "cr_id": plan.cr_id,
                "work_id": plan.work_id,
                "plan_digest": plan_digest,
                "authorization_id": authorization.authorization_id,
                "cutover_intent_digest": plan.cutover_intent_digest,
                "targets": [target.as_dict() for target in plan.targets],
                "completed_at": _now_utc(),
            }
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(
                receipt_path,
                json.dumps(
                    receipt,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
        except Exception as exc:
            rollback_errors: list[str] = []
            for target in reversed(applied):
                try:
                    if target.logical_ref == _rollback_failure_ref:
                        raise RuntimeError("injected rollback failure")
                    if target.before is None:
                        target.path.unlink(missing_ok=True)
                    else:
                        _atomic_write(target.path, target.before)
                    current = _optional_text(target.path)
                    if (
                        canonical_digest(current if current is not None else "")
                        != target.before_digest
                    ):
                        raise RuntimeError("rollback digest mismatch")
                except Exception as rollback_exc:
                    rollback_errors.append(f"{target.logical_ref}: {rollback_exc}")
            durable_refs = [
                target.logical_ref
                for target in plan.targets
                if canonical_digest(_optional_text(target.path) or "") == target.after_digest
            ]
            status = "PARTIAL" if rollback_errors else "RECOVERED"
            manifest["recovery_state"] = status.lower()
            manifest["durable_leaf_refs"] = durable_refs
            manifest["updated_at"] = _now_utc()
            try:
                _atomic_write(
                    manifest_path,
                    json.dumps(
                        manifest,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                )
            except OSError as manifest_exc:
                rollback_errors.append(f"private transaction manifest: {manifest_exc}")
            if status == "RECOVERED":
                shutil.rmtree(transaction_dir, ignore_errors=True)
            result = {
                "status": status,
                "reason": str(exc),
                "transaction_id": transaction_id,
                "authorization_id": authorization.authorization_id,
                "plan_digest": plan_digest,
                "mutation_count": len(applied),
                "rollback_errors": rollback_errors,
                "durable_leaf_refs": durable_refs,
            }
            if status == "PARTIAL":
                result["recovery_contract"] = {
                    "receipt_ref": (
                        f"private://c0-cutover-v2/transactions/{transaction_id}/manifest.json"
                    ),
                    "required_precondition": (
                        "停止所有 process writer，按 reverse rollback_order "
                        "恢复 before_digest 后重新生成全新 plan/authorization"
                    ),
                    "retry_allowed_after": "all target before_digest restored",
                }
            return result
        shutil.rmtree(transaction_dir, ignore_errors=True)
        return {
            "status": "PASS",
            "decision": "PASS",
            "transaction_id": transaction_id,
            "authorization_id": authorization.authorization_id,
            "plan_digest": plan_digest,
            "cutover_intent_digest": plan.cutover_intent_digest,
            "mutation_count": len(plan.targets),
            "path_refs": list(plan.mutation_allowlist),
            "receipt_ref": (f"private://c0-cutover-v2/receipts/{receipt_path.name}"),
        }
    except (OSError, ProcessRouteError, TypeError, ValueError) as exc:
        return {
            "status": "BLOCKED",
            "reason": str(exc).replace(str(release_root), "<release-root>"),
            "mutation_count": 0,
        }
    finally:
        if lock_path is not None:
            lock_path.unlink(missing_ok=True)
