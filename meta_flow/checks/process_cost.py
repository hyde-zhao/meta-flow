"""CR 发布包的机器派生过程成本报告。"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.work.model import load_work
from meta_flow.work.usage import load_usage

ARTIFACT_BUDGETS_REF = "process/policies/ARTIFACT-BUDGETS.json"
DEVELOPMENT_PLAN_REF = "process/DEVELOPMENT-PLAN.yaml"
CHECKPOINT_LEDGER_REF = "process/state/CHECKPOINT-LEDGER.ndjson"
GATE_LEDGER_REF = "process/state/GATE-LEDGER.ndjson"
HANDOFF_LEDGER_REF = "process/state/HANDOFF-LEDGER.ndjson"
READ_EXPANSION_LEDGER_REF = "process/state/READ-EXPANSION-LEDGER.ndjson"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RELEASE_ACTIONS = {"qualification", "build", "canary", "cp8", "release"}


@dataclass(frozen=True)
class SourceEvidenceV1:
    ref: str
    digest: str
    status: str = "available"

    def as_dict(self) -> dict[str, str]:
        return {"ref": self.ref, "digest": self.digest, "status": self.status}


@dataclass(frozen=True)
class ProcessCostInputV1:
    """完成聚合前的 typed、可复算输入；集合均使用稳定排序 tuple。"""

    cr_id: str
    package_id: str
    work_ids: tuple[str, ...]
    story_ids: tuple[str, ...]
    feature_refs: tuple[str, ...]
    lld_refs: tuple[str, ...]
    context_refs: tuple[str, ...]
    checkpoint_refs: tuple[str, ...]
    result_refs: tuple[str, ...]
    result_reference_count: int
    handoff_count: int
    return_count: int
    phase_handoff_count: int
    phase_return_count: int
    reads: int
    writes: int
    check_groups: int
    token_count: int | None
    token_measurement_status: str
    token_unavailable_reason: str
    expanded_reads: int
    actual_mutations: int
    semantic_noops: int
    source_bytes: int
    changed_release_paths: int
    changed_process_paths: int
    validation_layer_executions: tuple[tuple[str, int], ...]
    retry_count: int
    rework_count: int
    harness_errors: tuple[str, ...]
    release_action_attempts: tuple[tuple[str, int], ...]
    intermediate_release_count: int
    breaking_change_count: int
    process_artifact_count: int
    product_artifact_count: int
    source_evidence: tuple[SourceEvidenceV1, ...]
    telemetry_complete: bool
    terminal_cohort_size: int = 0
    hard_mode_approval_ref: str = ""


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_source(
    project_root: Path,
    logical_ref: str,
    evidence: list[SourceEvidenceV1],
) -> tuple[Path, bytes]:
    path = _resolve_runtime_ref(project_root, logical_ref)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"PROCESS_COST_SOURCE_MISSING:{logical_ref}")
    raw = path.read_bytes()
    evidence.append(SourceEvidenceV1(logical_ref, _digest_bytes(raw)))
    return path, raw


def _read_optional_ledger(
    project_root: Path,
    logical_ref: str,
    evidence: list[SourceEvidenceV1],
) -> list[dict[str, Any]]:
    path = _resolve_runtime_ref(project_root, logical_ref)
    if not path.exists():
        evidence.append(SourceEvidenceV1(logical_ref, canonical_digest([]), "not-present"))
        return []
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"PROCESS_COST_SOURCE_INVALID:{logical_ref}")
    raw = path.read_bytes()
    evidence.append(SourceEvidenceV1(logical_ref, _digest_bytes(raw)))
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"PROCESS_COST_LEDGER_INVALID:{logical_ref}:{line_number}"
            ) from exc
        if not isinstance(item, dict):
            raise ValueError(f"PROCESS_COST_LEDGER_INVALID:{logical_ref}:{line_number}")
        events.append(item)
    return events


def _git_inventory(root: Path, *, label: str) -> tuple[tuple[str, ...], SourceEvidenceV1]:
    completed = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "-uall"],
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise ValueError(f"PROCESS_COST_GIT_INVENTORY_UNAVAILABLE:{label}")
    entries = [entry for entry in completed.stdout.split(b"\0") if entry]
    paths = tuple(
        sorted(
            {
                entry[3:].decode("utf-8", errors="surrogateescape")
                for entry in entries
                if len(entry) > 3
            }
        )
    )
    return paths, SourceEvidenceV1(
        f"git-status:{label}", _digest_bytes(completed.stdout)
    )


def _event_matches(event: dict[str, Any], cr_id: str, work_ids: set[str]) -> bool:
    return event.get("cr_id") == cr_id or event.get("work_id") in work_ids


def _safe_result_ref(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("process/"):
        return None
    if "\\" in value or "://" in value or any(
        part in {"", ".", ".."} for part in value.split("/")
    ):
        return None
    return value


def _collect_harness_errors(
    project_root: Path,
    result_refs: tuple[str, ...],
    evidence: list[SourceEvidenceV1],
) -> tuple[str, ...]:
    errors: set[str] = set()
    for result_ref in result_refs:
        path, raw = _read_source(project_root, result_ref, evidence)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"PROCESS_COST_RESULT_INVALID:{result_ref}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"PROCESS_COST_RESULT_INVALID:{result_ref}")
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            if item.get("status") == "CHECK_HARNESS_ERROR":
                errors.add(str(item.get("id") or path.name))
    return tuple(sorted(errors))


def collect_process_cost_input(project_root: Path, cr_id: str) -> ProcessCostInputV1:
    """只读取声明的 canonical refs；不通过目录 sibling discovery 推测对象。"""

    root = project_root.resolve()
    if not _ID_RE.fullmatch(cr_id):
        raise ValueError("PROCESS_COST_CR_ID_INVALID")
    evidence: list[SourceEvidenceV1] = []
    plan_path, _plan_raw = _read_source(root, DEVELOPMENT_PLAN_REF, evidence)
    plan = load_yaml_object(plan_path)
    packages = plan.get("change_sets")
    if not isinstance(packages, list):
        raise ValueError("PROCESS_COST_CHANGE_SETS_MISSING")
    matches = [item for item in packages if isinstance(item, dict) and item.get("cr_id") == cr_id]
    if len(matches) != 1:
        raise ValueError("PROCESS_COST_RELEASE_PACKAGE_IDENTITY_INVALID")
    package = matches[0]
    work_ids = tuple(sorted(set(str(item) for item in package.get("work_ids") or [])))
    story_ids = tuple(sorted(set(str(item) for item in package.get("story_ids") or [])))
    if not work_ids or not story_ids:
        raise ValueError("PROCESS_COST_RELEASE_PACKAGE_EMPTY")

    story_records = [
        story
        for wave in plan.get("waves") or []
        if isinstance(wave, dict)
        for story in wave.get("stories") or []
        if isinstance(story, dict) and story.get("story_id") in story_ids
    ]
    if {str(item.get("story_id")) for item in story_records} != set(story_ids):
        raise ValueError("PROCESS_COST_STORY_PLAN_INCOMPLETE")
    feature_refs = tuple(
        sorted(
            {
                str(Path(ref).parent)
                for story in story_records
                for ref in story.get("feature_design_refs") or []
                if isinstance(ref, str) and ref.startswith("process/")
            }
        )
    )
    lld_refs = tuple(
        sorted(
            {
                str((story.get("lld_gate") or {}).get("evidence_ref"))
                for story in story_records
                if isinstance(story.get("lld_gate"), dict)
                and (story.get("lld_gate") or {}).get("evidence_ref")
            }
        )
    )
    output_files = {
        str(path)
        for story in story_records
        for path in story.get("output_files") or []
        if isinstance(path, str)
    }

    process_marker = _resolve_runtime_ref(root, "process/.meta-flow-process.yaml")
    process_root = process_marker.parent
    reads = writes = check_groups = 0
    human_interactions = design_revisions = qa_attempts = final_full_suites = 0
    token_total = 0
    token_status = "measured"
    token_reasons: list[str] = []
    for work_id in work_ids:
        work = load_work(process_root, work_id)
        work_ref = f"process/works/{work_id}/WORK.yaml"
        work_path = process_root / "works" / work_id / "WORK.yaml"
        evidence.append(SourceEvidenceV1(work_ref, _digest_bytes(work_path.read_bytes())))
        usage = load_usage(process_root, work)
        usage_path = process_root / work.usage_ref
        if usage_path.is_file():
            evidence.append(
                SourceEvidenceV1(
                    "process/" + work.usage_ref,
                    _digest_bytes(usage_path.read_bytes()),
                )
            )
        else:
            token_status = "unavailable"
            token_reasons.append(f"usage ledger not present:{work_id}")
            evidence.append(
                SourceEvidenceV1(
                    "process/" + work.usage_ref,
                    canonical_digest([]),
                    "not-present",
                )
            )
        for event in usage.events:
            reads += event.reads
            writes += event.writes
            check_groups += event.check_groups
            human_interactions += event.human_interactions
            design_revisions += event.design_revisions
            qa_attempts += event.qa_attempts
            final_full_suites += event.final_full_suites
            if event.token_measurement_status == "unavailable":
                token_status = "unavailable"
                token_reasons.append(event.unavailable_reason)
            elif token_status != "unavailable" and event.token_measurement_status == "proxy":
                token_status = "proxy"
            token_total += int(event.tokens or 0)

    checkpoint_events = _read_optional_ledger(root, CHECKPOINT_LEDGER_REF, evidence)
    gate_events = _read_optional_ledger(root, GATE_LEDGER_REF, evidence)
    handoff_events = _read_optional_ledger(root, HANDOFF_LEDGER_REF, evidence)
    matched_checkpoint_events = [
        event for event in checkpoint_events if _event_matches(event, cr_id, set(work_ids))
    ]
    matched_gate_events = [
        event for event in gate_events if _event_matches(event, cr_id, set(work_ids))
    ]
    matched_handoff_events = [
        event for event in handoff_events if _event_matches(event, cr_id, set(work_ids))
    ]
    handoff_refs = {
        ref
        for event in matched_handoff_events
        if isinstance((ref := event.get("handoff_ref")), str) and ref
    }
    return_refs = {
        ref
        for event in matched_handoff_events
        if isinstance((ref := event.get("return_ref")), str) and ref
    }
    phase_handoff_count = sum(ref.startswith("process/phases/") for ref in handoff_refs)
    phase_return_count = sum(ref.startswith("process/phases/") for ref in return_refs)
    context_refs = tuple(
        sorted(
            {
                ref
                for event in (*matched_checkpoint_events, *matched_gate_events)
                if isinstance((ref := event.get("context_ref")), str)
                and ref.startswith("process/")
            }
        )
    )
    checkpoint_refs = tuple(
        sorted(
            {
                ref
                for event in (*matched_checkpoint_events, *matched_gate_events)
                if isinstance((ref := event.get("checkpoint_ref")), str)
                and ref.startswith("process/")
            }
        )
    )
    result_reference_values = [
        safe
        for event in (*matched_checkpoint_events, *matched_gate_events)
        for raw_ref in (event.get("result_ref"), event.get("auto_result_ref"))
        if (safe := _safe_result_ref(raw_ref)) is not None
    ]
    result_refs = tuple(sorted(set(result_reference_values)))
    harness_errors = _collect_harness_errors(root, result_refs, evidence)

    read_expansion_events = _read_optional_ledger(
        root, READ_EXPANSION_LEDGER_REF, evidence
    )
    context_set = set(context_refs)
    expanded_reads = sum(
        1
        for event in read_expansion_events
        if event.get("context_ref") in context_set
        or _event_matches(event, cr_id, set(work_ids))
    )
    actions = {action: 0 for action in sorted(_RELEASE_ACTIONS)}
    intermediate_release_count = 0
    breaking_change_count = 0
    for event in (*matched_checkpoint_events, *matched_gate_events):
        if event.get("event_type") == "release_action_attempt":
            action = str(event.get("action") or "")
            if action in actions:
                actions[action] += 1
            if action == "release" and event.get("version") not in {None, "0.6.1"}:
                intermediate_release_count += 1
        if event.get("event_type") == "breaking_change_detected":
            breaking_change_count += 1
    mutation_counts = [
        count
        for event in (
            *matched_checkpoint_events,
            *matched_gate_events,
            *matched_handoff_events,
        )
        if type(count := event.get("mutation_count")) is int and count >= 0
    ]

    changed_release_path_refs, release_inventory = _git_inventory(root, label="release")
    changed_process_path_refs, process_inventory = _git_inventory(
        process_root, label="process"
    )
    evidence.extend((release_inventory, process_inventory))
    available_process_refs = {
        item.ref
        for item in evidence
        if item.status == "available" and item.ref.startswith("process/")
    }
    source_bytes = sum(
        path.stat().st_size
        for ref in available_process_refs
        if (path := _resolve_runtime_ref(root, ref)).is_file()
    )
    declared_process_refs = (
        set(context_refs)
        | set(checkpoint_refs)
        | set(result_refs)
        | set(lld_refs)
        | {DEVELOPMENT_PLAN_REF}
        | {
            f"process/works/{work_id}/WORK.yaml"
            for work_id in work_ids
        }
    )
    changed_process_refs = {f"process/{ref}" for ref in changed_process_path_refs}
    process_artifacts = changed_process_refs.intersection(declared_process_refs) | {
        ref
        for ref in changed_process_refs
        if any(token in ref for token in ("CR072", "CR-072", "cr072"))
    }
    product_artifacts = set(changed_release_path_refs).intersection(output_files)
    return ProcessCostInputV1(
        cr_id=cr_id,
        package_id=f"{cr_id}-0.6.1-release-package",
        work_ids=work_ids,
        story_ids=story_ids,
        feature_refs=feature_refs,
        lld_refs=lld_refs,
        context_refs=context_refs,
        checkpoint_refs=checkpoint_refs,
        result_refs=result_refs,
        result_reference_count=len(result_reference_values),
        handoff_count=len(handoff_refs),
        return_count=len(return_refs),
        phase_handoff_count=phase_handoff_count,
        phase_return_count=phase_return_count,
        reads=reads,
        writes=writes,
        check_groups=check_groups,
        token_count=None if token_status == "unavailable" else token_total,
        token_measurement_status=token_status,
        token_unavailable_reason="; ".join(dict.fromkeys(token_reasons)),
        expanded_reads=expanded_reads,
        actual_mutations=sum(mutation_counts),
        semantic_noops=sum(count == 0 for count in mutation_counts),
        source_bytes=source_bytes,
        changed_release_paths=len(changed_release_path_refs),
        changed_process_paths=len(changed_process_path_refs),
        validation_layer_executions=(("recorded_check_groups", check_groups),),
        retry_count=qa_attempts,
        rework_count=design_revisions,
        harness_errors=harness_errors,
        release_action_attempts=tuple(sorted(actions.items())),
        intermediate_release_count=intermediate_release_count,
        breaking_change_count=breaking_change_count,
        process_artifact_count=len(process_artifacts),
        product_artifact_count=len(product_artifacts),
        source_evidence=tuple(sorted(evidence, key=lambda item: item.ref)),
        telemetry_complete=token_status != "unavailable",
    )


def _limit_findings(
    value: int,
    rule: dict[str, Any],
    *,
    field: str,
) -> list[str]:
    findings: list[str] = []
    if type(rule.get("exact")) is int and value != rule["exact"]:
        findings.append(f"{field}:expected={rule['exact']}:actual={value}")
    if type(rule.get("min")) is int and value < rule["min"]:
        findings.append(f"{field}:min={rule['min']}:actual={value}")
    if type(rule.get("max")) is int and value > rule["max"]:
        findings.append(f"{field}:max={rule['max']}:actual={value}")
    return findings


def _budgeted_context_capsules(
    context_refs: tuple[str, ...], rule: dict[str, Any]
) -> tuple[tuple[str, ...], dict[str, int]]:
    """按 policy 的阶段身份统计 Capsule，不把 Story packet/CP0 混入阶段预算。"""

    raw_stages = rule.get("included_stages")
    if raw_stages is None and rule.get("identity") == "one-per-CP2-CP3-CP5-CP7-CP8":
        raw_stages = ["CP2", "CP3", "CP5", "CP7", "CP8"]
    if not isinstance(raw_stages, list) or not raw_stages or any(
        not isinstance(stage, str) or not re.fullmatch(r"CP[0-9]+", stage)
        for stage in raw_stages
    ):
        raise ValueError("PROCESS_COST_CONTEXT_BUDGET_IDENTITY_INVALID")
    stages = tuple(dict.fromkeys(raw_stages))
    counts = {stage: 0 for stage in stages}
    selected: list[str] = []
    for ref in context_refs:
        prefix = "process/context/"
        if not ref.startswith(prefix):
            continue
        relative = ref.removeprefix(prefix)
        if "/" in relative:
            continue
        for stage in stages:
            if re.match(rf"^{re.escape(stage)}(?:[-.]|$)", relative):
                selected.append(ref)
                counts[stage] += 1
                break
    return tuple(sorted(selected)), counts


def build_process_cost_report(
    value: ProcessCostInputV1,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """构造稳定报告；0.6.1 只 hard structural/safety，经验指标 measure-only。"""

    profiles = policy.get("release_package_profiles")
    profile = profiles.get(value.cr_id) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        raise ValueError("PROCESS_COST_POLICY_PROFILE_MISSING")
    hard_findings: list[str] = []
    hard_findings.extend(
        _limit_findings(1, dict(profile.get("formal_cr") or {}), field="formal_cr")
    )
    hard_findings.extend(
        _limit_findings(
            len(value.work_ids),
            dict(profile.get("implementation_work") or {}),
            field="implementation_work",
        )
    )
    hard_findings.extend(
        _limit_findings(
            len(value.story_ids),
            dict(profile.get("process_story") or {}),
            field="process_story",
        )
    )
    hard_findings.extend(
        _limit_findings(
            len(
                _budgeted_context_capsules(
                    value.context_refs,
                    dict(profile.get("context_capsule") or {}),
                )[0]
            ),
            dict(profile.get("context_capsule") or {}),
            field="context_capsule",
        )
    )
    context_rule = dict(profile.get("context_capsule") or {})
    budgeted_context_refs, context_stage_counts = _budgeted_context_capsules(
        value.context_refs, context_rule
    )
    max_per_stage = context_rule.get("max_per_stage")
    if type(max_per_stage) is int:
        for stage, count in context_stage_counts.items():
            if count > max_per_stage:
                hard_findings.append(
                    f"context_capsule:{stage}:max={max_per_stage}:actual={count}"
                )
    max_group = (profile.get("canonical_work_handoff_return_group") or {}).get(
        "max_per_work"
    )
    if type(max_group) is int:
        if value.handoff_count - value.phase_handoff_count > max_group * len(value.work_ids):
            hard_findings.append("handoff_group:limit-exceeded")
        if value.return_count - value.phase_return_count > max_group * len(value.work_ids):
            hard_findings.append("return_group:limit-exceeded")
    phase_max = (profile.get("canonical_phase_handoff_return_group") or {}).get("max")
    if type(phase_max) is int:
        if value.phase_handoff_count > phase_max:
            hard_findings.append("phase_handoff_group:limit-exceeded")
        if value.phase_return_count > phase_max:
            hard_findings.append("phase_return_group:limit-exceeded")
    if value.harness_errors:
        hard_findings.append(
            "unresolved_harness_errors:" + ",".join(value.harness_errors)
        )
    release_attempts = dict(value.release_action_attempts)
    for action in _RELEASE_ACTIONS:
        if release_attempts.get(action, 0) > 1:
            hard_findings.append(f"{action}_attempt_count:>1")
    if value.intermediate_release_count != 0:
        hard_findings.append("intermediate_release_count:nonzero")
    if value.breaking_change_count != 0:
        hard_findings.append("breaking_change_count:nonzero")

    ratio = (
        value.process_artifact_count / value.product_artifact_count
        if value.product_artifact_count
        else None
    )
    reuse_denominator = value.result_reference_count
    evidence_reuse_ratio = (
        (reuse_denominator - len(value.result_refs)) / reuse_denominator
        if reuse_denominator
        else None
    )
    no_op_denominator = value.actual_mutations + value.semantic_noops
    no_op_ratio = (
        value.semantic_noops / no_op_denominator if no_op_denominator else None
    )
    soft_risks: list[str] = []
    soft_max = (profile.get("process_to_product_artifact_ratio") or {}).get(
        "soft_max"
    )
    if ratio is not None and isinstance(soft_max, (int, float)) and ratio > soft_max:
        soft_risks.append(
            f"PROCESS_PRODUCT_RATIO_HIGH:limit={float(soft_max)}:actual={ratio:.6f}"
        )
    if value.token_measurement_status == "unavailable":
        soft_risks.append("TOKEN_TELEMETRY_UNAVAILABLE")

    hard_mode_eligible = (
        value.terminal_cohort_size >= 3
        and value.telemetry_complete
        and not value.harness_errors
        and not hard_findings
        and bool(value.hard_mode_approval_ref)
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "ProcessCostReportV1",
        "identity": {
            "cr_id": value.cr_id,
            "package_id": value.package_id,
            "work_ids": list(value.work_ids),
            "profile": "measure-only-v1",
            "policy_digest": canonical_digest(policy),
            "source_fingerprint": canonical_digest(
                [item.as_dict() for item in value.source_evidence]
            ),
        },
        "counts": {
            "formal_cr": 1,
            "work": len(value.work_ids),
            "story": len(value.story_ids),
            "feature": len(value.feature_refs),
            "lld": len(value.lld_refs),
            "context": len(value.context_refs),
            "budgeted_context_capsule": len(budgeted_context_refs),
            "checkpoint": len(value.checkpoint_refs),
            "handoff": value.handoff_count,
            "return": value.return_count,
            "result": len(value.result_refs),
        },
        "io": {
            "reads": value.reads,
            "expanded_reads": value.expanded_reads,
            "writes": value.writes,
            "actual_mutations": value.actual_mutations,
            "semantic_noops": value.semantic_noops,
            "source_bytes": value.source_bytes,
            "written_bytes": None,
            "written_bytes_status": "unavailable",
            "changed_release_paths": value.changed_release_paths,
            "changed_process_paths": value.changed_process_paths,
        },
        "validation": {
            "layer_executions": dict(value.validation_layer_executions),
            "retry_count": value.retry_count,
            "rework_count": value.rework_count,
            "harness_errors": list(value.harness_errors),
        },
        "usage": {
            "tokens": value.token_count,
            "token_measurement_status": value.token_measurement_status,
            "token_unavailable_reason": value.token_unavailable_reason or None,
            "elapsed_seconds": None,
            "elapsed_status": "unavailable",
        },
        "release": {
            **release_attempts,
            "intermediate_release": value.intermediate_release_count,
            "breaking_change": value.breaking_change_count,
        },
        "ratios": {
            "process_product_artifact": ratio,
            "evidence_reuse": evidence_reuse_ratio,
            "semantic_noop": no_op_ratio,
        },
        "mode": {
            "empirical": "measure-only",
            "structural_safety": "hard",
            "hard_mode_eligible": hard_mode_eligible,
            "hard_mode_reason": "candidate" if hard_mode_eligible else "MODE_NOT_CALIBRATED",
            "terminal_cohort_size": value.terminal_cohort_size,
        },
        "source_evidence": [item.as_dict() for item in value.source_evidence],
        "hard_findings": sorted(set(hard_findings)),
        "soft_risks": sorted(set(soft_risks)),
        "decision": (
            "BLOCKED"
            if hard_findings
            else "PASS_WITH_RISK"
            if soft_risks
            else "PASS"
        ),
    }
    report["report_digest"] = canonical_digest(report)
    return report


def load_process_cost_policy(project_root: Path) -> dict[str, Any]:
    path = _resolve_runtime_ref(project_root.resolve(), ARTIFACT_BUDGETS_REF)
    if path.is_symlink() or not path.is_file():
        raise ValueError("PROCESS_COST_POLICY_MISSING")
    return load_yaml_object(path)
