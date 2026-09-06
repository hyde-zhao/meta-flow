"""关闭后 CR 的跨对象一致性检查。"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from meta_flow.checks import cr_tracking
from meta_flow.design import feature_registry
from meta_flow.project import governance as project_governance
from meta_flow.project.model import is_safe_ref
from meta_flow.project.process_route import _resolve_runtime_ref, require_process_route
from meta_flow.project.scale import _load_compatible_yaml
from meta_flow.workflow.cr_model import parse_frontmatter, parse_inline_list
from meta_flow.workflow.legacy_evidence_registry import (
    FormalCRPartitionReportV1,
    load_formal_cr_partition,
)

TERMINAL_ISSUE_STATUSES = frozenset({"resolved", "closed", "cancelled", "superseded"})
TERMINAL_WORK_STATUSES = frozenset({"completed", "cancelled"})
PASS_DECISIONS = frozenset({"PASS", "PASS_WITH_RISK"})
READY_RELEASE_DECISIONS = frozenset({"READY", "READY_WITH_RISK"})
PUBLIC_OPERATION_DECLARATIONS = (("check.post-close", ("meta-flow", "check", "post-close")),)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    ref: str


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class PostCloseProfileV1:
    allowed_readiness: tuple[str, ...] = ("READY", "READY_WITH_RISK")
    allowed_phase_statuses: tuple[str, ...] = ("active", "completed")
    issue_refs_required: bool = False
    follow_up_tracking_required: bool = False
    follow_up_candidate_required: bool = False


@dataclass(frozen=True)
class RequiredCapabilitySetV1:
    source_ref: str
    source_digest: str
    approved_scope_ref: str
    approved_scope_digest: str
    approval_identity: str
    required_aliases: tuple[str, ...]

    @property
    def required_set_digest(self) -> str:
        return _digest(
            {
                "schema_version": 1,
                "kind": "RequiredCapabilitySetV1",
                "source_ref": self.source_ref,
                "source_digest": self.source_digest,
                "approved_scope_ref": self.approved_scope_ref,
                "approved_scope_digest": self.approved_scope_digest,
                "approval_identity": self.approval_identity,
                "required_aliases": list(self.required_aliases),
            }
        )


@dataclass(frozen=True)
class CapabilityResolutionV1:
    required_set_digest: str
    registry_digest: str
    resolved_aliases: tuple[str, ...]
    unresolved_aliases: tuple[str, ...]

    @property
    def decision(self) -> str:
        return "UNRESOLVED" if self.unresolved_aliases else "RESOLVED"


def _load_text(project_root: Path, logical_ref: str) -> tuple[Path | None, str]:
    if not is_safe_ref(logical_ref, prefix="process"):
        return None, ""
    path = _resolve_runtime_ref(project_root, logical_ref)
    if path.is_symlink() or not path.is_file():
        return None, ""
    return path, path.read_text(encoding="utf-8")


def _load_mapping(project_root: Path, logical_ref: str) -> tuple[Path | None, dict[str, Any]]:
    path, text = _load_text(project_root, logical_ref)
    if path is None:
        return None, {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = _load_compatible_yaml(text)
    return path, payload if isinstance(payload, dict) else {}


def _frontmatter_mapping(
    project_root: Path, logical_ref: str
) -> tuple[Path | None, dict[str, Any], str]:
    path, text = _load_text(project_root, logical_ref)
    if path is None:
        return None, {}, ""
    return path, parse_frontmatter(text), text


def _finding(findings: list[Finding], code: str, message: str, ref: str) -> None:
    findings.append(Finding(code=code, message=message, ref=ref))


def _index_item(index: dict[str, Any], cr_id: str) -> dict[str, Any]:
    items = index.get("items")
    if not isinstance(items, list):
        return {}
    return next(
        (item for item in items if isinstance(item, dict) and str(item.get("id") or "") == cr_id),
        {},
    )


def _resolved_capabilities(payload: dict[str, Any]) -> set[str]:
    resolution = payload.get("impact_capability_resolution")
    resolution = resolution if isinstance(resolution, dict) else {}
    results = resolution.get("results")
    if not isinstance(results, list):
        return set()
    return {
        str(item.get("input_ref"))
        for item in results
        if isinstance(item, dict)
        if item.get("status") == "resolved" and item.get("input_ref")
    }


def _canonical_process_ref(value: Any) -> str:
    ref = str(value or "").strip()
    return ref if ref.startswith("process/") else f"process/{ref}" if ref else ""


def check_post_close(
    project_root: Path,
    cr_id: str,
    *,
    release_context_ref: str = "process/release/RELEASE-CONTEXT.yaml",
    partition_report: FormalCRPartitionReportV1 | None = None,
) -> dict[str, Any]:
    """以 Release Context 的 closure_reconciliation 为清单执行零写检查。"""

    root = project_root.resolve()
    route = require_process_route(root)
    findings: list[Finding] = []
    checked_refs: set[str] = set()
    if partition_report is None:
        _registry, _snapshot, partition_report = load_formal_cr_partition(
            root,
            consumer_id="post-close",
        )
    partition_snapshot_digest = partition_report.snapshot_digest
    if partition_report.decision != "PASS":
        _finding(
            findings,
            "POST_CLOSE_FORMAL_PARTITION_BLOCKED",
            ",".join(partition_report.reason_codes),
            partition_report.evidence_refs[0]
            if partition_report.evidence_refs
            else "process/changes",
        )

    release_path, release = _load_mapping(root, release_context_ref)
    checked_refs.add(release_context_ref)
    if release_path is None:
        _finding(
            findings,
            "POST_CLOSE_RELEASE_CONTEXT_MISSING",
            "Release Context 不存在或路径不安全",
            release_context_ref,
        )
        return _report(
            cr_id,
            release_context_ref,
            checked_refs,
            findings,
            partition_snapshot_digest=partition_snapshot_digest,
        )
    if str(release.get("cr_id") or "") != cr_id:
        _finding(
            findings,
            "POST_CLOSE_RELEASE_OWNER_MISMATCH",
            "Release Context cr_id 与目标 CR 不一致",
            release_context_ref,
        )
    if str(release.get("status") or "") != "released_remote_verified_native_closed":
        _finding(
            findings,
            "POST_CLOSE_RELEASE_CONTEXT_OPEN",
            "Release Context 尚未进入 native-closed 终态",
            release_context_ref,
        )
    execution = release.get("release_execution")
    execution = execution if isinstance(execution, dict) else {}
    if str(execution.get("status") or "") != "RELEASED_REMOTE_VERIFIED_NATIVE_CLOSED":
        _finding(
            findings,
            "POST_CLOSE_RELEASE_EXECUTION_OPEN",
            "release_execution 尚未声明 native close 完成",
            release_context_ref,
        )

    reconciliation = release.get("closure_reconciliation")
    reconciliation = reconciliation if isinstance(reconciliation, dict) else {}
    profile = PostCloseProfileV1(
        issue_refs_required=reconciliation.get("issue_policy") == "required",
        follow_up_tracking_required=reconciliation.get("follow_up_policy")
        in {"required", "candidate_required"},
        follow_up_candidate_required=reconciliation.get("follow_up_policy") == "candidate_required",
    )
    if reconciliation.get("schema_version") != 1 or reconciliation.get("status") != "completed":
        _finding(
            findings,
            "POST_CLOSE_MANIFEST_INCOMPLETE",
            "closure_reconciliation 必须是 completed 的 v1 清单",
            release_context_ref,
        )

    native_close = reconciliation.get("native_close")
    native_close = native_close if isinstance(native_close, dict) else {}
    cr_ref = str(native_close.get("cr_ref") or f"process/changes/{cr_id}.md")
    cr_path, cr_fields, cr_text = _frontmatter_mapping(root, cr_ref)
    checked_refs.add(cr_ref)
    if cr_ref not in set(partition_report.native_formal_cr_refs):
        _finding(
            findings,
            "POST_CLOSE_CR_NOT_IN_NATIVE_PARTITION",
            "Release Context cr_ref 不属于 authoritative native formal CR partition",
            cr_ref,
        )
    if cr_path is None:
        _finding(findings, "POST_CLOSE_FORMAL_CR_MISSING", "正式 CR 不存在或路径不安全", cr_ref)
    else:
        actual_tuple = (
            str(cr_fields.get("lifecycle_status") or ""),
            str(cr_fields.get("readiness_status") or ""),
            str(cr_fields.get("gate_status") or ""),
        )
        if not (
            actual_tuple[0] == "closed"
            # CR-078（S4-2）：frontmatter 为 canonical 小写，profile 常量为
            # 大写——比较前归一化（0.6.5 此处对合法终态误报 mismatch）。
            and actual_tuple[1].upper() in profile.allowed_readiness
            and actual_tuple[2] == "cp8_closed"
        ):
            _finding(
                findings,
                "POST_CLOSE_CR_TUPLE_MISMATCH",
                f"正式 CR 终态 tuple 不一致: {actual_tuple}",
                cr_ref,
            )

    phase_ref = str(native_close.get("phase_ref") or "")
    phase_path, phase = _load_mapping(root, phase_ref) if phase_ref else (None, {})
    if phase_ref:
        checked_refs.add(phase_ref)
    phase_status = str(phase.get("status") or "")
    if phase_path is None:
        _finding(
            findings,
            "POST_CLOSE_PHASE_MISSING",
            "承载 Phase 不存在或路径不安全",
            phase_ref or release_context_ref,
        )
    else:
        phase_errors = project_governance.validate_phase_payload(phase)
        if phase_errors:
            _finding(
                findings,
                "POST_CLOSE_PHASE_INVALID",
                "; ".join(item.message for item in phase_errors),
                phase_ref,
            )
        phase_id = str(phase.get("phase_id") or "")
        expected_phase_ref = f"process/phases/{phase_id}/PHASE.yaml" if phase_id else ""
        if (
            str(phase.get("project_id") or "") != route.project_id
            or _canonical_process_ref(phase_ref) != expected_phase_ref
        ):
            _finding(
                findings,
                "POST_CLOSE_PHASE_OWNER_MISMATCH",
                "承载 Phase 的 project_id/phase_id 与 Release Context 绑定不一致",
                phase_ref,
            )
        if phase_status not in profile.allowed_phase_statuses:
            _finding(
                findings,
                "POST_CLOSE_PHASE_STATUS_INVALID",
                f"承载 Phase 状态不允许关闭后核验: {phase_status}",
                phase_ref,
            )
        elif phase_status == "active":
            project_ref = "process/PROJECT.yaml"
            project_path, project = _load_mapping(root, project_ref)
            checked_refs.add(project_ref)
            if (
                project_path is None
                or str(project.get("project_id") or "") != route.project_id
                or str(project.get("status") or "") != "active"
                or _canonical_process_ref(project.get("active_phase_ref"))
                != _canonical_process_ref(phase_ref)
            ):
                _finding(
                    findings,
                    "POST_CLOSE_ACTIVE_PHASE_BINDING_MISMATCH",
                    "active Phase 未被 PROJECT.active_phase_ref 真实绑定",
                    project_ref,
                )

    work_refs = native_close.get("work_refs")
    work_refs = work_refs if isinstance(work_refs, list) else []
    # CR-078（S4-3）：无 Work 的 release CR（Story 直排实施）可通过
    # work_binding_policy: not_required 显式声明豁免；默认 required 保持
    # 既有 CR 的强绑定语义。
    work_binding_required = (
        str(reconciliation.get("work_binding_policy") or "required") == "required"
    )
    if work_binding_required and not work_refs:
        _finding(
            findings,
            "POST_CLOSE_WORK_BINDING_MISSING",
            "native_close 未声明 Work refs",
            release_context_ref,
        )
    for raw_ref in work_refs:
        work_ref = str(raw_ref)
        checked_refs.add(work_ref)
        work_path, work = _load_mapping(root, work_ref)
        if work_path is None or str(work.get("status") or "") not in TERMINAL_WORK_STATUSES:
            _finding(
                findings, "POST_CLOSE_WORK_NOT_TERMINAL", "Work 未处于 terminal 状态", work_ref
            )

    current_cp8 = reconciliation.get("current_cp8")
    current_cp8 = current_cp8 if isinstance(current_cp8, dict) else {}
    cp8_result_ref = str(current_cp8.get("result_ref") or "")
    cp8_checkpoint_ref = str(current_cp8.get("checkpoint_ref") or "")
    result_path, result = _load_mapping(root, cp8_result_ref) if cp8_result_ref else (None, {})
    checkpoint_path, checkpoint_fields, _ = (
        _frontmatter_mapping(root, cp8_checkpoint_ref) if cp8_checkpoint_ref else (None, {}, "")
    )
    checked_refs.update(ref for ref in (cp8_result_ref, cp8_checkpoint_ref) if ref)
    if result_path is None:
        _finding(
            findings,
            "POST_CLOSE_CP8_RESULT_MISSING",
            "current CP8 result 不存在",
            cp8_result_ref or release_context_ref,
        )
    else:
        if str(result.get("cr_id") or "") != cr_id or str(result.get("checkpoint") or "") != "CP8":
            _finding(
                findings,
                "POST_CLOSE_CP8_OWNER_MISMATCH",
                "current CP8 result owner/checkpoint 不一致",
                cp8_result_ref,
            )
        if str(result.get("decision") or "").upper() not in PASS_DECISIONS:
            _finding(
                findings, "POST_CLOSE_CP8_NOT_PASS", "current CP8 result 不是 PASS", cp8_result_ref
            )
        if str(result.get("release_decision") or "").upper() not in READY_RELEASE_DECISIONS:
            _finding(
                findings,
                "POST_CLOSE_CP8_NOT_READY",
                "current CP8 release_decision 不是 READY",
                cp8_result_ref,
            )
    if checkpoint_path is None or str(checkpoint_fields.get("status") or "").lower() != "approved":
        _finding(
            findings,
            "POST_CLOSE_CP8_HUMAN_GATE_NOT_APPROVED",
            "current CP8 人工门未 approved",
            cp8_checkpoint_ref or release_context_ref,
        )
    if cr_text and (cp8_result_ref not in cr_text or cp8_checkpoint_ref not in cr_text):
        _finding(
            findings,
            "POST_CLOSE_CP8_CURRENT_BINDING_STALE",
            "正式 CR 的 CP8 导航未绑定 current result/checkpoint",
            cr_ref,
        )
    predecessor_refs = current_cp8.get("predecessor_result_refs")
    predecessor_refs = predecessor_refs if isinstance(predecessor_refs, list) else []
    if cp8_result_ref in {str(ref) for ref in predecessor_refs}:
        _finding(
            findings,
            "POST_CLOSE_CP8_LINEAGE_ALIAS",
            "current CP8 不得同时被声明为 predecessor",
            release_context_ref,
        )
    for raw_ref in predecessor_refs:
        predecessor_ref = str(raw_ref)
        checked_refs.add(predecessor_ref)
        predecessor_path, _ = _load_mapping(root, predecessor_ref)
        if predecessor_path is None:
            _finding(
                findings,
                "POST_CLOSE_CP8_PREDECESSOR_MISSING",
                "predecessor 失败证据未保留",
                predecessor_ref,
            )

    issue_refs = reconciliation.get("resolved_issue_refs")
    issue_refs = issue_refs if isinstance(issue_refs, list) else []
    if not issue_refs and profile.issue_refs_required:
        _finding(
            findings,
            "POST_CLOSE_ISSUE_BINDING_MISSING",
            "closure_reconciliation 未声明 resolved issue",
            release_context_ref,
        )
    for raw_ref in issue_refs:
        issue_ref = str(raw_ref)
        checked_refs.add(issue_ref)
        issue_path, issue_fields, _ = _frontmatter_mapping(root, issue_ref)
        if (
            issue_path is None
            or str(issue_fields.get("status") or "").lower() not in TERMINAL_ISSUE_STATUSES
        ):
            _finding(
                findings,
                "POST_CLOSE_ISSUE_NOT_TERMINAL",
                "关联 ISSUE 未进入 terminal 状态",
                issue_ref,
            )

    tracking_ref = str(reconciliation.get("follow_up_tracking_ref") or "")
    tracking_path, tracking_fields, _ = (
        _frontmatter_mapping(root, tracking_ref) if tracking_ref else (None, {}, "")
    )
    if tracking_ref:
        checked_refs.add(tracking_ref)
    if tracking_ref and (
        tracking_path is None or str(tracking_fields.get("source_cr") or "") != cr_id
    ):
        _finding(
            findings,
            "POST_CLOSE_FOLLOW_UP_OWNER_MISSING",
            "follow-up tracking 不存在或 source_cr 不匹配",
            tracking_ref or release_context_ref,
        )
    elif (
        tracking_ref
        and profile.follow_up_candidate_required
        and not any(
            row.lifecycle_status == "candidate"
            for row in cr_tracking.parse_structured_follow_up_rows(tracking_path)
        )
    ):
        _finding(
            findings,
            "POST_CLOSE_FOLLOW_UP_CANDIDATE_MISSING",
            "follow-up tracking 没有 candidate 行",
            tracking_ref,
        )
    elif not tracking_ref and profile.follow_up_tracking_required:
        _finding(
            findings,
            "POST_CLOSE_FOLLOW_UP_OWNER_MISSING",
            "profile 要求 follow-up tracking，但 Release Context 未声明",
            release_context_ref,
        )

    required_capability_refs = reconciliation.get("required_capability_refs")
    required_capability_refs = (
        [str(ref) for ref in required_capability_refs]
        if isinstance(required_capability_refs, list)
        else []
    )
    approved_capability_refs = parse_inline_list(cr_fields.get("impact_capability_refs", ""))
    if set(approved_capability_refs) != set(required_capability_refs):
        _finding(
            findings,
            "POST_CLOSE_REQUIRED_CAPABILITY_SCOPE_MISMATCH",
            "Release Context required capability set 与 approved CR scope 不一致",
            cr_ref,
        )
    required_set = RequiredCapabilitySetV1(
        source_ref=release_context_ref,
        source_digest=_digest(reconciliation),
        approved_scope_ref=cr_ref,
        approved_scope_digest=hashlib.sha256(cr_text.encode("utf-8")).hexdigest(),
        approval_identity=str(
            reconciliation.get("approval_ref") or release.get("release_decision_ref") or cr_ref
        ),
        # approved CR scope 是 capability membership 的唯一 owner；Release Context
        # 只能提供完全相等的 closure 投影，不能在关闭阶段自行扩大集合。
        required_aliases=tuple(sorted(set(approved_capability_refs))),
    )
    capability_resolution = feature_registry.resolve_refs(
        root,
        list(required_set.required_aliases),
        kind="capability",
        mode="enforce",
    )
    unresolved = [
        item
        for item in capability_resolution.get("results", [])
        if isinstance(item, dict) and item.get("status") != "resolved"
    ]
    registry_ref = "process/docs/design/CAPABILITY-REGISTRY.yaml"
    registry_path, registry_payload = _load_mapping(root, registry_ref)
    registry_digest = _digest(registry_payload) if registry_path is not None else ""
    resolution = CapabilityResolutionV1(
        required_set_digest=required_set.required_set_digest,
        registry_digest=registry_digest,
        resolved_aliases=tuple(
            sorted(
                set(required_set.required_aliases)
                - {str(item.get("input_ref") or "") for item in unresolved}
            )
        ),
        unresolved_aliases=tuple(sorted(str(item.get("input_ref") or "") for item in unresolved)),
    )
    if unresolved:
        _finding(
            findings,
            "POST_CLOSE_CAPABILITY_UNRESOLVED",
            f"required capability refs 未完全解析: {len(unresolved)}",
            "process/docs/design/CAPABILITY-REGISTRY.yaml",
        )

    summary_ref = f"process/changes/summaries/{cr_id}.summary.json"
    index_ref = "process/changes/CR-INDEX.json"
    _, summary = _load_mapping(root, summary_ref)
    _, index = _load_mapping(root, index_ref)
    checked_refs.update({summary_ref, index_ref, "process/docs/design/CAPABILITY-REGISTRY.yaml"})
    if set(required_set.required_aliases) - _resolved_capabilities(summary):
        _finding(
            findings,
            "POST_CLOSE_SUMMARY_CAPABILITY_STALE",
            "CR summary capability projection 尚未收敛",
            summary_ref,
        )
    index_entry = _index_item(index, cr_id)
    if set(required_set.required_aliases) - _resolved_capabilities(index_entry):
        _finding(
            findings,
            "POST_CLOSE_INDEX_CAPABILITY_STALE",
            "CR index capability projection 尚未收敛",
            index_ref,
        )

    state_ref = "process/state/STATE.current.json"
    _, state = _load_mapping(root, state_ref)
    checked_refs.add(state_ref)
    if str(state.get("active_change") or "") == cr_id:
        _finding(
            findings,
            "POST_CLOSE_ACTIVE_CHANGE_STALE",
            "STATE.active_change 仍指向已关闭 CR",
            state_ref,
        )

    return _report(
        cr_id,
        release_context_ref,
        checked_refs,
        findings,
        partition_snapshot_digest=partition_snapshot_digest,
        profile=profile,
        required_set=required_set,
        capability_resolution=resolution,
    )


def _report(
    cr_id: str,
    release_context_ref: str,
    checked_refs: set[str],
    findings: list[Finding],
    *,
    partition_snapshot_digest: str = "",
    profile: PostCloseProfileV1 | None = None,
    required_set: RequiredCapabilitySetV1 | None = None,
    capability_resolution: CapabilityResolutionV1 | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "PostCloseReconciliationCheckV1",
        "cr_id": cr_id,
        "release_context_ref": release_context_ref,
        "decision": "BLOCKED" if findings else "PASS",
        "partition_snapshot_digest": partition_snapshot_digest,
        "post_close_profile": (
            {
                **asdict(profile),
                "allowed_readiness": list(profile.allowed_readiness),
                "allowed_phase_statuses": list(profile.allowed_phase_statuses),
            }
            if profile is not None
            else {}
        ),
        "required_capability_set": (
            {
                **asdict(required_set),
                "required_aliases": list(required_set.required_aliases),
                "required_set_digest": required_set.required_set_digest,
            }
            if required_set is not None
            else {}
        ),
        "capability_resolution": (
            {
                **asdict(capability_resolution),
                "resolved_aliases": list(capability_resolution.resolved_aliases),
                "unresolved_aliases": list(capability_resolution.unresolved_aliases),
                "decision": capability_resolution.decision,
            }
            if capability_resolution is not None
            else {}
        ),
        "mutation_count": 0,
        "checked_refs": sorted(ref for ref in checked_refs if ref),
        "finding_count": len(findings),
        "findings": [asdict(item) for item in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate post-close CR/release/checkpoint/follow-up/capability convergence."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", dest="cr_id", required=True)
    parser.add_argument(
        "--release-context",
        default="process/release/RELEASE-CONTEXT.yaml",
    )
    parser.add_argument("--format", choices=("json", "text"), default="text")
    args = parser.parse_args(argv)
    try:
        result = check_post_close(
            args.project_root,
            args.cr_id,
            release_context_ref=args.release_context,
        )
    except (OSError, ValueError) as exc:
        result = {
            "schema_version": 1,
            "kind": "PostCloseReconciliationCheckV1",
            "cr_id": args.cr_id,
            "release_context_ref": args.release_context,
            "decision": "CHECK_HARNESS_ERROR",
            "mutation_count": 0,
            "finding_count": 1,
            "findings": [
                {
                    "code": "POST_CLOSE_CHECK_HARNESS_ERROR",
                    "message": str(exc),
                    "ref": args.release_context,
                }
            ],
        }
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{result['decision']}: {args.cr_id}; findings={result['finding_count']}")
        for item in result.get("findings", []):
            print(f"- {item['code']}: {item['message']} [{item['ref']}]")
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
