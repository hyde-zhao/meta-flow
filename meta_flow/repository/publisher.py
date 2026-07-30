"""一次只处理一个仓的 allowlist commit 与 exact-OID push。

已存在的远端分支只允许 fast-forward；不存在的远端分支只允许带空值 lease
的 create-only 首次 push，避免观测与写入之间的竞态覆盖。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.project.model import is_safe_ref
from meta_flow.project.process_route import ProcessRouteError, resolve_process_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.state import checkpoint_projection
from meta_flow.workspace.git_sync import query_exact_remote_ref, run_git

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_REF_RE = re.compile(r"^refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
_OID_RE = re.compile(r"^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$")
_PUBLICATION_CONTEXT_FIELDS = {
    "schema_version",
    "kind",
    "work_id",
    "cr_id",
    "canonical_refs",
    "targets",
}
_G2_CONTEXT_REF_KEYS = {
    "work",
    "route_plan",
    "formal_cr",
    "cr_summary",
    "cr_index",
    "cr_ledger",
    "cp8_result",
    "cp8_checkpoint",
    "gate_ledger",
}
_PUBLICATION_TARGET_FIELDS = {
    "operation",
    "repo_role",
    "remote",
    "ref",
    "preauthorized",
}


@dataclass(frozen=True)
class RepoObservation:
    root: Path
    branch: str
    head_oid: str
    changed_paths: tuple[str, ...]
    staged_paths: tuple[str, ...]


@dataclass(frozen=True)
class RepositoryAuthorization:
    authorization_id: str
    operation: str
    project_id: str
    work_id: str
    repo_role: str
    plan_digest: str
    expected_oid: str
    expires_at: str
    single_use: bool = True


@dataclass(frozen=True)
class PublicationEligibility:
    """由 WORK 快照和 route plan 交叉验证得到的 publication 前置结论。"""

    decision: str
    reason: str
    branch: str
    work_profile_digest: str
    route_plan_digest: str
    mutation_count: int = 0


@dataclass(frozen=True)
class PublicationEvidence:
    """供 plan 与 apply 同步重算的 canonical eligibility 证据引用。"""

    project_root: Path
    evidence_ref: str


@dataclass(frozen=True)
class PublicationContext:
    """稳定、可跟踪的发布上下文；动态事实由原生 producer 在每次 plan 时生成。"""

    project_root: Path
    context_ref: str


@dataclass(frozen=True)
class PublicationEligibilityPlanV1:
    """由当前原生真相动态生成的发布资格计划。"""

    work_id: str
    cr_id: str
    operation: str
    repo_role: str
    remote: str
    ref: str
    observed_oid: str
    scope_version: int
    scope_digest: str
    work_profile_digest: str
    route_plan_digest: str
    canonical_refs: dict[str, str]
    canonical_digests: dict[str, str]
    requested_target: dict[str, str]
    decision: str
    reason: str
    branch: str
    plan_digest: str
    mutation_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "PublicationEligibilityPlanV1",
            **self.__dict__,
        }


def _resolve_publication_ref(project_root: Path, logical_ref: str) -> Path:
    """所有 publication 证据均通过健康 binding 的 process resolver。"""

    if not logical_ref.startswith("process/"):
        raise ValueError("publication evidence contains an unsafe or empty ref")
    return resolve_process_ref(project_root, logical_ref)


def _load_publication_object(project_root: Path, logical_ref: str) -> dict[str, Any]:
    path = _resolve_publication_ref(project_root, logical_ref)
    if path.suffix.lower() == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
    else:
        value = load_yaml_object(path)
    if not isinstance(value, dict):
        raise ValueError(f"{logical_ref} must contain one mapping")
    return value


def _profile_snapshot(work: dict[str, Any], work_ref: str) -> dict[str, Any]:
    scope = work.get("scope") or {}
    return {
        "work_id": str(work.get("work_id") or ""),
        "work_ref": work_ref,
        "kind": str(work.get("kind") or ""),
        "risk_profile": str(work.get("risk_profile") or ""),
        "risk_reason_codes": sorted(str(item) for item in work.get("risk_reason_codes") or []),
        "required_gates": sorted(str(item) for item in work.get("required_gates") or []),
        "scope_version": int(work.get("scope_version") or scope.get("version") or 0),
        "scope_digest": str(work.get("scope_digest") or scope.get("digest") or ""),
    }


def evaluate_publication_eligibility(
    *,
    project_root: Path,
    work_id: str,
    route_plan_ref: str,
    work_ref: str = "",
) -> PublicationEligibility:
    """只评估 WORK+route；G2 必须由 canonical evidence loader 补齐批准事实。"""
    logical_work_ref = work_ref or f"process/works/{work_id}/WORK.yaml"
    try:
        work = _load_publication_object(project_root, logical_work_ref)
        route = _load_publication_object(project_root, route_plan_ref)
    except (ProcessRouteError, OSError, ValueError, json.JSONDecodeError):
        return PublicationEligibility("BLOCKED", "ROUTE_PROFILE_UNTRUSTED", "", "", "")
    snapshot = _profile_snapshot(work, logical_work_ref)
    profile_digest, route_digest = _digest(snapshot), _digest(route)
    if (
        snapshot["work_id"] != work_id
        or not snapshot["scope_version"]
        or not snapshot["scope_digest"]
    ):
        return PublicationEligibility(
            "BLOCKED", "ROUTE_PROFILE_UNTRUSTED", "", profile_digest, route_digest
        )
    route_snapshot = route.get("work_profile_snapshot")
    route_profile_digest = str(route.get("work_profile_digest") or "")
    if route_snapshot != snapshot or route_profile_digest != profile_digest:
        return PublicationEligibility(
            "BLOCKED", "PROFILE_ROUTE_CONFLICT", "", profile_digest, route_digest
        )
    cp8 = (route.get("checkpoint_applicability") or {}).get("CP8") or {}
    profile = snapshot["risk_profile"]
    if profile == "G2":
        if not (cp8.get("applies") is True and cp8.get("human_gate") == "required"):
            return PublicationEligibility(
                "BLOCKED", "PROFILE_ROUTE_CONFLICT", "", profile_digest, route_digest
            )
        return PublicationEligibility(
            "BLOCKED", "CP8_REQUIRED", "G2_CP8_APPLIES", profile_digest, route_digest
        )
    canonical_na = (
        cp8.get("applies") is False
        and cp8.get("decision") in {"N/A", "NOT_APPLICABLE_BY_PROFILE"}
        and cp8.get("reason") == "profile-not-required"
    )
    if profile not in {"G0", "G1"} or snapshot["kind"] != "work" or not canonical_na:
        return PublicationEligibility(
            "BLOCKED", "PROFILE_ROUTE_CONFLICT", "", profile_digest, route_digest
        )
    if snapshot["risk_reason_codes"]:
        return PublicationEligibility(
            "BLOCKED", "RECLASSIFICATION_REQUIRED_G2", "", profile_digest, route_digest
        )
    return PublicationEligibility(
        "READY",
        "eligible_by_profile",
        "G0_G1_NOT_APPLICABLE_BY_PROFILE",
        profile_digest,
        route_digest,
    )


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    if match is None:
        raise ValueError(f"{path.name} has no frontmatter")
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _scope_allows_reads(work: dict[str, Any], refs: Iterable[str]) -> bool:
    scope = work.get("scope") or {}
    allowed = scope.get("allowed_reads") or work.get("allowed_reads") or []
    patterns = [str(item) for item in allowed]
    if not patterns:
        return False

    def candidates(logical_ref: str) -> tuple[str, ...]:
        # Publication evidence 使用 process/... 逻辑引用；WORK scope 的规范值则以
        # 过程仓根为基准，不携带 process/ 前缀。兼容历史上已经写入完整逻辑引用的
        # fixture，但不放宽到绝对路径、父目录或其他命名空间。
        if logical_ref.startswith("process/"):
            return logical_ref, logical_ref.removeprefix("process/")
        return (logical_ref,)

    return all(
        any(
            fnmatchcase(candidate, pattern) for candidate in candidates(ref) for pattern in patterns
        )
        for ref in refs
    )


def _target_is_authorized(
    policy: dict[str, Any],
    *,
    work_id: str,
    scope_version: int,
    scope_digest: str,
    operation: str,
    repo_role: str,
    remote: str,
    ref: str,
) -> bool:
    if (
        policy.get("decision") != "APPROVED"
        or str(policy.get("work_id") or "") != work_id
        or int(policy.get("scope_version") or 0) != scope_version
        or str(policy.get("scope_digest") or "") != scope_digest
    ):
        return False
    return any(
        isinstance(target, dict)
        and target.get("operation") == operation
        and target.get("repo_role") == repo_role
        and str(target.get("remote") or "") == remote
        and str(target.get("ref") or "") == ref
        and target.get("preauthorized") is True
        for target in policy.get("targets") or []
    )


def _g2_is_canonically_approved(
    *,
    project_root: Path,
    refs: dict[str, str],
    cr_id: str,
    work_id: str,
    scope_version: int,
    scope_digest: str,
) -> bool:
    projection = checkpoint_projection.load_checkpoint_projection(
        project_root,
        cr_id=cr_id,
        checkpoint="CP8",
        candidate_refs=(refs["cp8_result"],),
        resolver=_resolve_publication_ref,
    )
    head = projection.head("CP8")
    if projection.findings or head is None or head.result_ref != refs["cp8_result"]:
        return False
    result = head.result
    if (
        str(result.get("checkpoint") or "").upper() != "CP8"
        or str(result.get("decision") or "").upper() not in {"PASS", "PASS_WITH_RISK"}
        or not cr_id
        or str(result.get("work_id") or "") != work_id
        or int(result.get("scope_version") or 0) != scope_version
        or str(result.get("scope_digest") or "") != scope_digest
    ):
        return False
    checkpoint = _frontmatter(_resolve_publication_ref(project_root, refs["cp8_checkpoint"]))
    if (
        str(checkpoint.get("work_id") or "") != work_id
        or checkpoint.get("status", "").lower() not in {"approved", "approve"}
        or str(checkpoint.get("scope_digest") or "") != scope_digest
    ):
        return False

    from meta_flow.workflow.cr_lifecycle import project_native_cr_status

    projection = project_native_cr_status(project_root, cr_id=cr_id)
    if (
        projection.decision != "PASS"
        or projection.formal_cr_ref != refs["formal_cr"]
        or projection.summary_ref != refs["cr_summary"]
        or refs["cr_index"] != "process/changes/CR-INDEX.json"
        or refs["cr_ledger"] != "process/state/CR-LEDGER.ndjson"
        or projection.lifecycle_status != "closed"
        or projection.readiness_status not in {"ready", "ready_with_risk"}
        or projection.gate_status not in {"cp8_closed", "cp8_recovery_closed"}
    ):
        return False
    ledger_path = _resolve_publication_ref(project_root, refs["gate_ledger"])
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if (
            isinstance(event, dict)
            and event.get("event_type") == "human_gate_approval"
            and event.get("status") == "approved"
            and str(event.get("work_id") or "") == work_id
            and str(event.get("cr_id") or "") == cr_id
            and "CP8" in str(event.get("gate") or event.get("checkpoint") or "")
            and str(event.get("scope_digest") or "") == scope_digest
        ):
            return True
    return False


def build_publication_eligibility_plan(
    *,
    work_id: str,
    context: PublicationContext,
    operation: str,
    repo_role: str,
    observed_oid: str,
    remote: str = "",
    ref: str = "",
) -> PublicationEligibilityPlanV1:
    """从稳定 context 和当前原生真相生成一次零写发布资格计划。"""

    payload = _load_publication_object(context.project_root, context.context_ref)
    if set(payload) != _PUBLICATION_CONTEXT_FIELDS:
        raise ValueError("publication context fields mismatch")
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "PublicationContextV1"
        or str(payload.get("work_id") or "") != work_id
    ):
        raise ValueError("publication context identity mismatch")
    cr_id = str(payload.get("cr_id") or "")
    if not re.fullmatch(r"CR-\d{3,}", cr_id):
        raise ValueError("publication context cr_id is invalid")
    refs = payload.get("canonical_refs")
    if not isinstance(refs, dict) or set(refs) != _G2_CONTEXT_REF_KEYS:
        raise ValueError("publication context canonical ref set mismatch")
    normalized_refs = {key: str(value) for key, value in refs.items()}
    if any(
        not value.startswith("process/") or not is_safe_ref(value)
        for value in normalized_refs.values()
    ):
        raise ValueError("publication context contains unsafe canonical ref")

    work = _load_publication_object(context.project_root, normalized_refs["work"])
    route = _load_publication_object(
        context.project_root,
        normalized_refs["route_plan"],
    )
    snapshot = _profile_snapshot(work, normalized_refs["work"])
    profile_digest = _digest(snapshot)
    route_digest = _digest(route)
    if (
        snapshot["work_id"] != work_id
        or snapshot["risk_profile"] != "G2"
        or snapshot["kind"] != "cr"
        or not snapshot["scope_version"]
        or not snapshot["scope_digest"]
    ):
        raise ValueError("publication context WORK profile is not canonical G2")
    route_snapshot = route.get("work_profile_snapshot")
    route_profile_digest = str(route.get("work_profile_digest") or "")
    if (route_snapshot is None) != (not route_profile_digest):
        raise ValueError("route profile snapshot is partially populated")
    if route_snapshot is not None and (
        route_snapshot != snapshot or route_profile_digest != profile_digest
    ):
        raise ValueError("route profile snapshot diverges from current WORK")
    cp8_route = (route.get("checkpoint_applicability") or {}).get("CP8") or {}
    if (
        route.get("decision") not in {None, "PASS"}
        or route.get("blockers") not in (None, [])
        or cp8_route.get("applies") is not True
        or cp8_route.get("human_gate") != "required"
    ):
        raise ValueError("route plan is not trusted for G2 publication")

    all_refs = [context.context_ref, *normalized_refs.values()]
    if not _scope_allows_reads(work, all_refs):
        raise ValueError("publication context ref is outside WORK allowed_reads")
    canonical_digests = {
        key: _sha256_file(_resolve_publication_ref(context.project_root, logical_ref))
        for key, logical_ref in normalized_refs.items()
    }

    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("publication context targets must be non-empty")
    for target in targets:
        if not isinstance(target, dict) or set(target) != _PUBLICATION_TARGET_FIELDS:
            raise ValueError("publication context target fields mismatch")
    target_matches = any(
        target.get("operation") == operation
        and target.get("repo_role") == repo_role
        and str(target.get("remote") or "") == remote
        and str(target.get("ref") or "") == ref
        and target.get("preauthorized") is True
        for target in targets
    )
    if not target_matches:
        raise ValueError("publication context target is not preauthorized")
    if not _OID_RE.fullmatch(observed_oid):
        raise ValueError("publication context repository OID mismatch")

    approved = _g2_is_canonically_approved(
        project_root=context.project_root,
        refs=normalized_refs,
        cr_id=cr_id,
        work_id=work_id,
        scope_version=snapshot["scope_version"],
        scope_digest=snapshot["scope_digest"],
    )
    requested_target = {
        "operation": operation,
        "repo_role": repo_role,
        "remote": remote,
        "ref": ref,
    }
    decision = "READY" if approved else "BLOCKED"
    reason = "eligible_g2" if approved else "CP8_REQUIRED"
    digest_source = {
        "schema_version": 1,
        "kind": "PublicationEligibilityPlanV1",
        "work_id": work_id,
        "cr_id": cr_id,
        "operation": operation,
        "repo_role": repo_role,
        "remote": remote,
        "ref": ref,
        "observed_oid": observed_oid,
        "scope_version": snapshot["scope_version"],
        "scope_digest": snapshot["scope_digest"],
        "work_profile_digest": profile_digest,
        "route_plan_digest": route_digest,
        "canonical_refs": normalized_refs,
        "canonical_digests": canonical_digests,
        "requested_target": requested_target,
        "decision": decision,
        "reason": reason,
        "branch": "G2_CP8_APPLIES",
        "mutation_count": 0,
    }
    return PublicationEligibilityPlanV1(
        work_id=work_id,
        cr_id=cr_id,
        operation=operation,
        repo_role=repo_role,
        remote=remote,
        ref=ref,
        observed_oid=observed_oid,
        scope_version=snapshot["scope_version"],
        scope_digest=snapshot["scope_digest"],
        work_profile_digest=profile_digest,
        route_plan_digest=route_digest,
        canonical_refs=normalized_refs,
        canonical_digests=canonical_digests,
        requested_target=requested_target,
        decision=decision,
        reason=reason,
        branch="G2_CP8_APPLIES",
        plan_digest=_digest(digest_source),
    )


def _evaluate_publication_inputs(
    work_id: str,
    *,
    evidence: PublicationEvidence | None,
    context: PublicationContext | None,
    operation: str,
    repo_role: str,
    observed_oid: str,
    remote: str = "",
    ref: str = "",
) -> tuple[PublicationEligibility, PublicationEligibilityPlanV1 | None]:
    if evidence is not None and context is not None:
        return (
            PublicationEligibility(
                "BLOCKED",
                "PUBLICATION_INPUT_CONFLICT",
                "",
                "",
                "",
            ),
            None,
        )
    if context is None:
        return (
            _evaluate_evidence(
                work_id,
                evidence,
                operation=operation,
                repo_role=repo_role,
                observed_oid=observed_oid,
                remote=remote,
                ref=ref,
            ),
            None,
        )
    try:
        plan = build_publication_eligibility_plan(
            work_id=work_id,
            context=context,
            operation=operation,
            repo_role=repo_role,
            observed_oid=observed_oid,
            remote=remote,
            ref=ref,
        )
    except (
        ProcessRouteError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return (
            PublicationEligibility(
                "BLOCKED",
                "PUBLICATION_CONTEXT_UNTRUSTED",
                "",
                "",
                "",
            ),
            None,
        )
    return (
        PublicationEligibility(
            plan.decision,
            plan.reason,
            plan.branch,
            plan.work_profile_digest,
            plan.route_plan_digest,
        ),
        plan,
    )


def _evaluate_evidence(
    work_id: str,
    evidence: PublicationEvidence | None,
    *,
    operation: str,
    repo_role: str,
    observed_oid: str,
    remote: str = "",
    ref: str = "",
) -> PublicationEligibility:
    if evidence is None:
        return PublicationEligibility("BLOCKED", "PUBLICATION_EVIDENCE_REQUIRED", "", "", "")
    try:
        payload = _load_publication_object(evidence.project_root, evidence.evidence_ref)
        if (
            payload.get("schema_version") != 1
            or payload.get("evidence_kind") != "publication-eligibility"
        ):
            raise ValueError("unsupported publication evidence schema")
        if str(payload.get("work_id") or "") != work_id:
            raise ValueError("publication evidence work_id mismatch")
        refs = payload.get("canonical_refs") or {}
        digests = payload.get("canonical_digests") or {}
        if not isinstance(refs, dict) or not isinstance(digests, dict):
            raise ValueError("publication evidence refs/digests must be mappings")
        work_ref = str(refs.get("work") or "")
        route_plan_ref = str(refs.get("route_plan") or "")
        work = _load_publication_object(evidence.project_root, work_ref)
        route = _load_publication_object(evidence.project_root, route_plan_ref)
        snapshot = _profile_snapshot(work, work_ref)
        profile_digest = _digest(snapshot)
        route_digest = _digest(route)
        if (
            int(payload.get("scope_version") or 0) != snapshot["scope_version"]
            or str(payload.get("scope_digest") or "") != snapshot["scope_digest"]
            or str(payload.get("work_profile_digest") or "") != profile_digest
            or str(payload.get("route_plan_digest") or "") != route_digest
        ):
            raise ValueError("publication evidence scope/profile/route digest mismatch")
        required_ref_keys = {"work", "route_plan", "target_policy"}
        if snapshot["risk_profile"] == "G2":
            required_ref_keys |= {
                "formal_cr",
                "cr_summary",
                "cr_index",
                "cr_ledger",
                "cp8_result",
                "cp8_checkpoint",
                "gate_ledger",
            }
        if set(refs) != required_ref_keys or set(digests) != required_ref_keys:
            raise ValueError("publication evidence canonical ref set mismatch")
        all_refs = [evidence.evidence_ref, *(str(refs[key]) for key in sorted(refs))]
        if not _scope_allows_reads(work, all_refs):
            raise ValueError("publication evidence ref is outside WORK allowed_reads")
        for key, logical_ref in refs.items():
            if str(digests.get(key) or "") != _sha256_file(
                _resolve_publication_ref(evidence.project_root, str(logical_ref))
            ):
                raise ValueError(f"publication evidence canonical digest mismatch: {key}")
        repo_oids = payload.get("repo_oids") or {}
        if (
            not _OID_RE.fullmatch(observed_oid)
            or str(repo_oids.get(repo_role) or "") != observed_oid
        ):
            raise ValueError("publication evidence repository OID mismatch")
        requested_target = payload.get("requested_target") or {}
        if requested_target != {
            "operation": operation,
            "repo_role": repo_role,
            "remote": remote,
            "ref": ref,
        }:
            raise ValueError("publication evidence requested target mismatch")
        target_policy = _load_publication_object(evidence.project_root, str(refs["target_policy"]))
        target_matches = _target_is_authorized(
            target_policy,
            work_id=work_id,
            scope_version=snapshot["scope_version"],
            scope_digest=snapshot["scope_digest"],
            operation=operation,
            repo_role=repo_role,
            remote=remote,
            ref=ref,
        )
        if not target_matches:
            raise ValueError("publication evidence target is not preauthorized")
        base = evaluate_publication_eligibility(
            project_root=evidence.project_root,
            work_id=work_id,
            route_plan_ref=route_plan_ref,
            work_ref=work_ref,
        )
        if snapshot["risk_profile"] != "G2":
            return base
        if base.reason != "CP8_REQUIRED":
            return base
        cr_id, checkpoint, _subject_id = checkpoint_projection.load_checkpoint_identity(
            evidence.project_root,
            str(refs["cp8_result"]),
            resolver=_resolve_publication_ref,
        )
        if checkpoint != "CP8":
            raise ValueError("publication checkpoint result is not CP8")
        approved = _g2_is_canonically_approved(
            project_root=evidence.project_root,
            refs={key: str(value) for key, value in refs.items()},
            cr_id=cr_id,
            work_id=work_id,
            scope_version=snapshot["scope_version"],
            scope_digest=snapshot["scope_digest"],
        )
        return PublicationEligibility(
            "READY" if approved else "BLOCKED",
            "eligible_g2" if approved else "CP8_REQUIRED",
            "G2_CP8_APPLIES",
            profile_digest,
            route_digest,
        )
    except (ProcessRouteError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return PublicationEligibility("BLOCKED", "PUBLICATION_EVIDENCE_UNTRUSTED", "", "", "")


@dataclass(frozen=True)
class CommitPlan:
    project_id: str
    work_id: str
    repo_role: str
    repo_root: Path
    message: str
    expected_head_oid: str
    changed_paths: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    unexpected_paths: tuple[str, ...]
    decision: str
    reason: str
    plan_digest: str
    publication_evidence: PublicationEvidence | None = None
    publication_context: PublicationContext | None = None
    publication_eligibility: PublicationEligibility | None = None
    publication_eligibility_plan: PublicationEligibilityPlanV1 | None = None

    @property
    def blocked(self) -> bool:
        return self.decision == "BLOCKED"

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "repo_root": str(self.repo_root),
            "changed_paths": list(self.changed_paths),
            "allowed_paths": list(self.allowed_paths),
            "unexpected_paths": list(self.unexpected_paths),
            "mutation_count": 0,
            "publication_evidence": (
                None
                if self.publication_evidence is None
                else {
                    "project_root": str(self.publication_evidence.project_root),
                    "evidence_ref": self.publication_evidence.evidence_ref,
                }
            ),
            "publication_context": (
                None
                if self.publication_context is None
                else {
                    "project_root": str(self.publication_context.project_root),
                    "context_ref": self.publication_context.context_ref,
                }
            ),
            "publication_eligibility": None
            if self.publication_eligibility is None
            else self.publication_eligibility.__dict__,
            "publication_eligibility_plan": (
                None
                if self.publication_eligibility_plan is None
                else self.publication_eligibility_plan.as_dict()
            ),
        }


@dataclass(frozen=True)
class CommitReceipt:
    authorization_id: str
    project_id: str
    work_id: str
    repo_role: str
    before_oid: str
    after_oid: str
    committed_paths: tuple[str, ...]
    decision: str
    mutation_count: int


@dataclass(frozen=True)
class PushPlan:
    project_id: str
    work_id: str
    repo_role: str
    repo_root: Path
    remote: str
    ref: str
    local_oid: str
    expected_remote_oid: str
    observed_remote_oid: str
    decision: str
    reason: str
    argv: tuple[str, ...]
    plan_digest: str
    publication_evidence: PublicationEvidence | None = None
    publication_context: PublicationContext | None = None
    publication_eligibility: PublicationEligibility | None = None
    publication_eligibility_plan: PublicationEligibilityPlanV1 | None = None

    @property
    def blocked(self) -> bool:
        return self.decision == "BLOCKED"

    @property
    def authorization_expected_oid(self) -> str:
        return self.expected_remote_oid or "ABSENT"

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "repo_root": str(self.repo_root),
            "argv": list(self.argv),
            "authorization_expected_oid": self.authorization_expected_oid,
            "mutation_count": 0,
            "publication_evidence": (
                None
                if self.publication_evidence is None
                else {
                    "project_root": str(self.publication_evidence.project_root),
                    "evidence_ref": self.publication_evidence.evidence_ref,
                }
            ),
            "publication_context": (
                None
                if self.publication_context is None
                else {
                    "project_root": str(self.publication_context.project_root),
                    "context_ref": self.publication_context.context_ref,
                }
            ),
            "publication_eligibility": None
            if self.publication_eligibility is None
            else self.publication_eligibility.__dict__,
            "publication_eligibility_plan": (
                None
                if self.publication_eligibility_plan is None
                else self.publication_eligibility_plan.as_dict()
            ),
        }


@dataclass(frozen=True)
class PushReceipt:
    authorization_id: str
    project_id: str
    work_id: str
    repo_role: str
    remote: str
    ref: str
    before_oid: str
    after_oid: str
    local_oid: str
    decision: str
    mutation_count: int
    argv: tuple[str, ...]


@dataclass(frozen=True)
class PushSequenceResult:
    decision: str
    repository_status: dict[str, str]
    receipts: tuple[PushReceipt, ...]
    errors: dict[str, str]
    rollback_count: int = 0


@dataclass(frozen=True)
class RepositoryFailureReceipt:
    operation: str
    project_id: str
    work_id: str
    repo_role: str
    decision: str
    before_oid: str
    observed_oid: str
    staged_paths: tuple[str, ...]
    mutation_count: int
    failed_stage: str
    error: str
    recovery_route: str


class RepositoryApplyError(ValueError):
    def __init__(self, message: str, receipt: RepositoryFailureReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt


def _git_value(root: Path, args: list[str]) -> str:
    result = run_git(args, cwd=root)
    if not result.ok:
        return ""
    return result.stdout.strip()


def _nul_paths(root: Path, args: list[str]) -> tuple[str, ...]:
    result = run_git(args, cwd=root)
    if not result.ok:
        raise ValueError(result.stderr.strip() or "Git path observation failed")
    paths = [item for item in result.stdout.split("\0") if item]
    for path in paths:
        if not is_safe_ref(path):
            raise ValueError(f"Git reported unsafe path: {path}")
    return tuple(paths)


def observe_repo(root: Path) -> RepoObservation:
    resolved = root.resolve()
    top = _git_value(resolved, ["rev-parse", "--show-toplevel"])
    if not top or Path(top).resolve() != resolved:
        raise ValueError("repository root is missing or nested")
    unstaged = _nul_paths(resolved, ["diff", "--name-only", "-z"])
    staged = _nul_paths(resolved, ["diff", "--cached", "--name-only", "-z"])
    untracked = _nul_paths(resolved, ["ls-files", "--others", "--exclude-standard", "-z"])
    changed = tuple(sorted(set((*unstaged, *staged, *untracked))))
    return RepoObservation(
        root=resolved,
        branch=_git_value(resolved, ["branch", "--show-current"]),
        head_oid=_git_value(resolved, ["rev-parse", "--verify", "HEAD"]),
        changed_paths=changed,
        staged_paths=tuple(sorted(set(staged))),
    )


def _validate_identity(project_id: str, work_id: str, repo_role: str) -> None:
    for label, value in (
        ("project_id", project_id),
        ("work_id", work_id),
        ("repo_role", repo_role),
    ):
        if not _ID_RE.fullmatch(value):
            raise ValueError(f"{label} is invalid")


def _validate_paths(paths: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(sorted(set(paths)))
    if not normalized:
        raise ValueError("allowed_paths must not be empty")
    for path in normalized:
        if not is_safe_ref(path):
            raise ValueError(f"unsafe allowed path: {path}")
    return normalized


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def plan_commit(
    *,
    project_id: str,
    work_id: str,
    repo_role: str,
    repo_root: Path,
    allowed_paths: Iterable[str],
    message: str,
    expected_head_oid: str,
    publication_evidence: PublicationEvidence | None = None,
    publication_context: PublicationContext | None = None,
) -> CommitPlan:
    _validate_identity(project_id, work_id, repo_role)
    if not _OID_RE.fullmatch(expected_head_oid):
        raise ValueError("expected_head_oid must be one exact full OID")
    if not message.strip() or "\n" in message or "\r" in message:
        raise ValueError("commit message must be one non-empty line")
    allowed = _validate_paths(allowed_paths)
    observation = observe_repo(repo_root)
    unexpected = tuple(path for path in observation.changed_paths if path not in allowed)
    reasons: list[str] = []
    if observation.head_oid != expected_head_oid:
        reasons.append("head_oid_mismatch")
    if not observation.branch:
        reasons.append("detached_head")
    if not observation.changed_paths:
        reasons.append("no_changes")
    if unexpected:
        reasons.append("unexpected_paths")
    if any(path not in allowed for path in observation.staged_paths):
        reasons.append("unexpected_staged_paths")
    eligibility, eligibility_plan = _evaluate_publication_inputs(
        work_id,
        evidence=publication_evidence,
        context=publication_context,
        operation="commit",
        repo_role=repo_role,
        observed_oid=observation.head_oid,
    )
    if eligibility.decision != "READY":
        reasons.append(eligibility.reason)
    decision = "BLOCKED" if reasons else "READY"
    digest_source = {
        "schema_version": 1,
        "project_id": project_id,
        "work_id": work_id,
        "repo_role": repo_role,
        "repo_root": str(observation.root),
        "message": message,
        "expected_head_oid": expected_head_oid,
        "branch": observation.branch,
        "changed_paths": observation.changed_paths,
        "staged_paths": observation.staged_paths,
        "allowed_paths": allowed,
        "unexpected_paths": unexpected,
        "decision": decision,
        "reasons": reasons,
        "publication_eligibility": eligibility.__dict__,
        "publication_eligibility_plan": (
            None if eligibility_plan is None else eligibility_plan.as_dict()
        ),
    }
    return CommitPlan(
        project_id=project_id,
        work_id=work_id,
        repo_role=repo_role,
        repo_root=observation.root,
        message=message,
        expected_head_oid=expected_head_oid,
        changed_paths=observation.changed_paths,
        allowed_paths=allowed,
        unexpected_paths=unexpected,
        decision=decision,
        reason=",".join(reasons) if reasons else "ready",
        plan_digest=_digest(digest_source),
        publication_evidence=publication_evidence,
        publication_context=publication_context,
        publication_eligibility=eligibility,
        publication_eligibility_plan=eligibility_plan,
    )


def _validate_authorization(
    authorization: RepositoryAuthorization,
    *,
    operation: str,
    project_id: str,
    work_id: str,
    repo_role: str,
    plan_digest: str,
    expected_oid: str,
) -> None:
    _validate_identity(project_id, work_id, repo_role)
    if not _ID_RE.fullmatch(authorization.authorization_id):
        raise ValueError("authorization_id is invalid")
    if authorization.single_use is not True:
        raise ValueError("repository authorization must be single-use")
    authorization_binds_absence = (
        operation == "push" and expected_oid == "ABSENT" and authorization.expected_oid == "ABSENT"
    )
    if not authorization_binds_absence and not _OID_RE.fullmatch(authorization.expected_oid):
        raise ValueError(
            "repository authorization expected_oid must be one exact full OID "
            "or ABSENT for a create-only push"
        )
    expected = (operation, project_id, work_id, repo_role, plan_digest, expected_oid)
    actual = (
        authorization.operation,
        authorization.project_id,
        authorization.work_id,
        authorization.repo_role,
        authorization.plan_digest,
        authorization.expected_oid,
    )
    if actual != expected:
        raise ValueError("repository authorization does not match operation/plan/OID")
    if not isinstance(authorization.expires_at, str):
        raise ValueError("authorization expires_at is invalid")
    try:
        expiry = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("authorization expires_at is invalid") from exc
    if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
        raise ValueError("repository authorization is expired")


def apply_commit(plan: CommitPlan, authorization: RepositoryAuthorization) -> CommitReceipt:
    if plan.blocked:
        raise ValueError(f"commit plan is blocked: {plan.reason}")
    fresh = plan_commit(
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        repo_root=plan.repo_root,
        allowed_paths=plan.allowed_paths,
        message=plan.message,
        expected_head_oid=plan.expected_head_oid,
        publication_evidence=plan.publication_evidence,
        publication_context=plan.publication_context,
    )
    if fresh.plan_digest != plan.plan_digest:
        raise ValueError("commit plan is stale")
    _validate_authorization(
        authorization,
        operation="commit",
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        plan_digest=plan.plan_digest,
        expected_oid=plan.expected_head_oid,
    )
    add_result = run_git(["add", "--", *plan.changed_paths], cwd=plan.repo_root)
    if not add_result.ok:
        message = add_result.stderr.strip() or "git add failed"
        after_failure = observe_repo(plan.repo_root)
        raise RepositoryApplyError(
            message,
            RepositoryFailureReceipt(
                operation="commit",
                project_id=plan.project_id,
                work_id=plan.work_id,
                repo_role=plan.repo_role,
                decision="PARTIAL" if after_failure.staged_paths else "FAILED",
                before_oid=plan.expected_head_oid,
                observed_oid=after_failure.head_oid,
                staged_paths=after_failure.staged_paths,
                mutation_count=1 if after_failure.staged_paths else 0,
                failed_stage="git_add",
                error=message,
                recovery_route="inspect-index-and-replan; no automatic reset/rollback",
            ),
        )
    staged = _nul_paths(plan.repo_root, ["diff", "--cached", "--name-only", "-z"])
    if tuple(sorted(staged)) != tuple(sorted(plan.changed_paths)):
        message = "staged paths do not exactly match planned changed paths"
        raise RepositoryApplyError(
            message,
            RepositoryFailureReceipt(
                operation="commit",
                project_id=plan.project_id,
                work_id=plan.work_id,
                repo_role=plan.repo_role,
                decision="PARTIAL",
                before_oid=plan.expected_head_oid,
                observed_oid=observe_repo(plan.repo_root).head_oid,
                staged_paths=staged,
                mutation_count=1,
                failed_stage="staged_path_verification",
                error=message,
                recovery_route="inspect-index-and-replan; no automatic reset/rollback",
            ),
        )
    commit_result = run_git(["commit", "-m", plan.message], cwd=plan.repo_root)
    if not commit_result.ok:
        message = commit_result.stderr.strip() or "git commit failed"
        after_failure = observe_repo(plan.repo_root)
        raise RepositoryApplyError(
            message,
            RepositoryFailureReceipt(
                operation="commit",
                project_id=plan.project_id,
                work_id=plan.work_id,
                repo_role=plan.repo_role,
                decision="PARTIAL",
                before_oid=plan.expected_head_oid,
                observed_oid=after_failure.head_oid,
                staged_paths=after_failure.staged_paths,
                mutation_count=1,
                failed_stage="git_commit",
                error=message,
                recovery_route="fix-commit-precondition-and-replan; preserve staged truth",
            ),
        )
    after = observe_repo(plan.repo_root)
    if not after.head_oid or after.head_oid == plan.expected_head_oid:
        raise ValueError("commit did not create one new HEAD")
    return CommitReceipt(
        authorization_id=authorization.authorization_id,
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        before_oid=plan.expected_head_oid,
        after_oid=after.head_oid,
        committed_paths=plan.changed_paths,
        decision="PASS",
        mutation_count=1,
    )


def _validate_remote_ref(remote: str, ref: str) -> None:
    if not remote or remote.startswith("-") or any(char in remote for char in "\x00\r\n"):
        raise ValueError("remote is invalid")
    if not _SAFE_REF_RE.fullmatch(ref) or ".." in ref or ref.endswith("/"):
        raise ValueError("ref must be one safe refs/heads ref")


def plan_push(
    *,
    project_id: str,
    work_id: str,
    repo_role: str,
    repo_root: Path,
    remote: str,
    ref: str,
    expected_remote_oid: str,
    publication_evidence: PublicationEvidence | None = None,
    publication_context: PublicationContext | None = None,
) -> PushPlan:
    _validate_identity(project_id, work_id, repo_role)
    _validate_remote_ref(remote, ref)
    if expected_remote_oid and not _OID_RE.fullmatch(expected_remote_oid):
        raise ValueError("expected_remote_oid must be one exact full OID")
    observation = observe_repo(repo_root)
    remote_observation = query_exact_remote_ref(observation.root, remote, ref)
    reasons: list[str] = []
    if observation.changed_paths:
        reasons.append("dirty_repository")
    if not observation.head_oid:
        reasons.append("local_head_missing")
    if remote_observation.decision == "PRESENT":
        if remote_observation.oid != expected_remote_oid:
            reasons.append("expected_remote_oid_mismatch")
    elif remote_observation.decision == "ABSENT":
        if expected_remote_oid:
            reasons.append("remote_ref_absent")
    else:
        reasons.append("remote_ref_observation_unknown")
    if observation.head_oid and remote_observation.decision == "PRESENT":
        ancestor = run_git(
            ["merge-base", "--is-ancestor", remote_observation.oid, observation.head_oid],
            cwd=observation.root,
        )
        if not ancestor.ok:
            reasons.append("not_fast_forward")
    eligibility, eligibility_plan = _evaluate_publication_inputs(
        work_id,
        evidence=publication_evidence,
        context=publication_context,
        operation="push",
        repo_role=repo_role,
        observed_oid=observation.head_oid,
        remote=remote,
        ref=ref,
    )
    if eligibility.decision != "READY":
        reasons.append(eligibility.reason)
    decision = "BLOCKED" if reasons else "READY"
    if remote_observation.decision == "ABSENT" and not expected_remote_oid:
        argv = (
            "push",
            f"--force-with-lease={ref}:",
            remote,
            f"{observation.head_oid}:{ref}",
        )
    else:
        argv = ("push", remote, f"{observation.head_oid}:{ref}")
    digest_source = {
        "schema_version": 1,
        "project_id": project_id,
        "work_id": work_id,
        "repo_role": repo_role,
        "repo_root": str(observation.root),
        "remote": remote,
        "ref": ref,
        "local_oid": observation.head_oid,
        "expected_remote_oid": expected_remote_oid,
        "observed_remote_state": remote_observation.decision,
        "observed_remote_oid": remote_observation.oid,
        "decision": decision,
        "reasons": reasons,
        "argv": argv,
        "publication_eligibility": eligibility.__dict__,
        "publication_eligibility_plan": (
            None if eligibility_plan is None else eligibility_plan.as_dict()
        ),
    }
    return PushPlan(
        project_id=project_id,
        work_id=work_id,
        repo_role=repo_role,
        repo_root=observation.root,
        remote=remote,
        ref=ref,
        local_oid=observation.head_oid,
        expected_remote_oid=expected_remote_oid,
        observed_remote_oid=remote_observation.oid,
        decision=decision,
        reason=",".join(reasons) if reasons else "ready",
        argv=argv,
        plan_digest=_digest(digest_source),
        publication_evidence=publication_evidence,
        publication_context=publication_context,
        publication_eligibility=eligibility,
        publication_eligibility_plan=eligibility_plan,
    )


def apply_push(plan: PushPlan, authorization: RepositoryAuthorization) -> PushReceipt:
    if plan.blocked:
        raise ValueError(f"push plan is blocked: {plan.reason}")
    fresh = plan_push(
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        repo_root=plan.repo_root,
        remote=plan.remote,
        ref=plan.ref,
        expected_remote_oid=plan.expected_remote_oid,
        publication_evidence=plan.publication_evidence,
        publication_context=plan.publication_context,
    )
    if fresh.plan_digest != plan.plan_digest:
        raise ValueError("push plan is stale")
    _validate_authorization(
        authorization,
        operation="push",
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        plan_digest=plan.plan_digest,
        expected_oid=plan.authorization_expected_oid,
    )
    result = run_git(list(plan.argv), cwd=plan.repo_root)
    after = query_exact_remote_ref(plan.repo_root, plan.remote, plan.ref)
    if not result.ok or after.decision != "PRESENT" or after.oid != plan.local_oid:
        message = result.stderr.strip() or "push did not publish the planned local OID"
        create_only_proven_no_mutation = (
            plan.authorization_expected_oid == "ABSENT"
            and not result.ok
            and after.decision in {"ABSENT", "PRESENT"}
            and after.oid != plan.local_oid
        )
        changed = (
            result.ok
            or (after.decision == "PRESENT" and after.oid == plan.local_oid)
            or after.decision == "UNKNOWN"
            or (
                not create_only_proven_no_mutation
                and after.decision == "PRESENT"
                and after.oid != plan.expected_remote_oid
            )
        )
        raise RepositoryApplyError(
            message,
            RepositoryFailureReceipt(
                operation="push",
                project_id=plan.project_id,
                work_id=plan.work_id,
                repo_role=plan.repo_role,
                decision="PARTIAL" if changed else "FAILED",
                before_oid=plan.expected_remote_oid,
                observed_oid=after.oid,
                staged_paths=(),
                mutation_count=1 if changed else 0,
                failed_stage="git_push_or_remote_verification",
                error=message,
                recovery_route="re-observe-remote-and-replan-only-failed-repository",
            ),
        )
    return PushReceipt(
        authorization_id=authorization.authorization_id,
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        remote=plan.remote,
        ref=plan.ref,
        before_oid=plan.expected_remote_oid,
        after_oid=after.oid,
        local_oid=plan.local_oid,
        decision="PASS",
        mutation_count=1,
        argv=result.argv,
    )


def execute_push_sequence(
    operations: Iterable[tuple[PushPlan, RepositoryAuthorization]],
) -> PushSequenceResult:
    items = tuple(operations)
    if not items:
        raise ValueError("push sequence must contain at least one repository")
    roles = tuple(plan.repo_role for plan, _authorization in items)
    if len(roles) != len(set(roles)):
        raise ValueError("push sequence repo_role values must be unique")
    statuses = {plan.repo_role: "not_started" for plan, _authorization in items}
    receipts: list[PushReceipt] = []
    errors: dict[str, str] = {}
    for plan, authorization in items:
        try:
            receipt = apply_push(plan, authorization)
        except ValueError as exc:
            statuses[plan.repo_role] = "failed"
            errors[plan.repo_role] = str(exc)
            break
        statuses[plan.repo_role] = "success"
        receipts.append(receipt)
    success_count = sum(value == "success" for value in statuses.values())
    if success_count == len(items):
        decision = "PASS"
    elif success_count:
        decision = "PARTIAL"
    else:
        decision = "FAILED"
    return PushSequenceResult(
        decision=decision,
        repository_status=statuses,
        receipts=tuple(receipts),
        errors=errors,
        rollback_count=0,
    )
