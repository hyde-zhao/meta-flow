"""Profile-driven validation task wrapper."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.project.process_route import _resolve_runtime_ref

VALIDATION_ROOT_REL = Path("process/validation")
EVIDENCE_ROOT_REL = Path("process/evidence")
RUN_LEDGER_NAME = "run-ledger.ndjson"
EVIDENCE_INDEX_NAME = "evidence-index.json"
RERUN_COMPARISON_NAME = "rerun-comparison.json"
ADMISSION_SUMMARY_NAME = "admission-summary.json"
FORBIDDEN_OPS_SUMMARY_NAME = "forbidden-ops-summary.json"

PROFILE_CONTRACTS: dict[str, dict[str, Any]] = {
    "real-lake-readonly": {
        "validation_mode": "runtime",
        "min_reruns": 2,
        "required_evidence": [
            "real_lake_validation",
            "historical_backtest",
            "oos_walkforward",
            "rerun_consistency",
            "admission_package",
        ],
        "allowed_capabilities": ["real_lake_read"],
        "forbidden_operations": [
            "lake_write",
            "catalog_write",
            "runtime_connection",
            "trading",
            "broker_access",
            "repository_publication",
        ],
    }
}


@dataclass(frozen=True)
class ValidationRunResult:
    run_ref: str
    status: str
    command: list[str]
    returncode: int | None
    stdout_sha256: str
    stderr_sha256: str
    stdout_excerpt: str
    stderr_excerpt: str


@dataclass(frozen=True)
class RecoveryAttemptPlan:
    work_id: str
    check_id: str
    attempt_key: str
    attempt_number: int
    failure_class: str
    input_digest: str
    scope_digest: str
    work_profile_digest: str
    action: str
    targeted_revalidation_only: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "work_id": self.work_id,
            "check_id": self.check_id,
            "attempt_key": self.attempt_key,
            "attempt_number": self.attempt_number,
            "failure_class": self.failure_class,
            "input_digest": self.input_digest,
            "scope_digest": self.scope_digest,
            "work_profile_digest": self.work_profile_digest,
            "action": self.action,
            "targeted_revalidation_only": self.targeted_revalidation_only,
        }


def recovery_attempt_key(
    *,
    work_id: str,
    check_id: str,
    input_digest: str,
    scope_digest: str,
    work_profile_digest: str,
) -> str:
    payload = {
        "work_id": work_id,
        "check_id": check_id,
        "input_digest": input_digest,
        "scope_digest": scope_digest,
        "work_profile_digest": work_profile_digest,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_recovery_attempt_plan(
    *,
    work_id: str,
    check_id: str,
    failure_class: str,
    input_digest: str,
    scope_digest: str,
    work_profile_digest: str,
    recovery_decision: dict[str, Any],
) -> RecoveryAttemptPlan:
    """把已获准的恢复决策转成一次受限 rerun；阻断决策不会产生 plan。"""

    if recovery_decision.get("decision") != "RECOVERY_ALLOWED":
        raise ValueError("recovery decision does not allow a rerun")
    attempts_completed = int(recovery_decision.get("attempts_completed", 0))
    effective_max = int(recovery_decision.get("effective_max_auto_recovery_attempts", 0))
    attempt_number = attempts_completed + 1
    if attempt_number > effective_max:
        raise ValueError("recovery attempt exceeds effective maximum")
    action = str(recovery_decision.get("next_action") or "")
    if action != "rerun_original_check_group":
        raise ValueError("recovery action must rerun the original check group")
    return RecoveryAttemptPlan(
        work_id=work_id,
        check_id=check_id,
        attempt_key=recovery_attempt_key(
            work_id=work_id,
            check_id=check_id,
            input_digest=input_digest,
            scope_digest=scope_digest,
            work_profile_digest=work_profile_digest,
        ),
        attempt_number=attempt_number,
        failure_class=failure_class,
        input_digest=input_digest,
        scope_digest=scope_digest,
        work_profile_digest=work_profile_digest,
        action=action,
        targeted_revalidation_only=bool(
            recovery_decision.get("targeted_revalidation_only")
        ),
    )


def build_recovery_receipt(
    plan: RecoveryAttemptPlan,
    *,
    result: str,
    evidence_refs: list[str],
    output_digest: str,
) -> dict[str, Any]:
    if result not in {"PASS", "FAIL", "BLOCKED"}:
        raise ValueError("recovery result must be PASS, FAIL, or BLOCKED")
    if not evidence_refs:
        raise ValueError("recovery receipt requires evidence refs")
    return {
        "schema_version": 1,
        "kind": "recovery-attempt-receipt",
        **plan.as_dict(),
        "result": result,
        "evidence_refs": list(evidence_refs),
        "output_digest": output_digest,
    }


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rel(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in value.strip())
    return "-".join(part for part in safe.split("-") if part) or "validation"


def _digest(text: str) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _excerpt(text: str, *, limit: int = 1000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...<truncated>"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _write_json(project_root: Path, path: Path, data: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return _rel(project_root, path)


def _append_ledger(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _parse_command(command: str) -> list[str]:
    parts = shlex.split(command)
    if not parts:
        raise ValueError("--command must not be empty")
    return parts


def _run_command(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )


def _planned_run(run_ref: str, command: list[str]) -> ValidationRunResult:
    return ValidationRunResult(
        run_ref=run_ref,
        status="PLANNED",
        command=command,
        returncode=None,
        stdout_sha256="",
        stderr_sha256="",
        stdout_excerpt="",
        stderr_excerpt="",
    )


def _executed_run(run_ref: str, command: list[str], completed: subprocess.CompletedProcess[str]) -> ValidationRunResult:
    return ValidationRunResult(
        run_ref=run_ref,
        status="PASS" if completed.returncode == 0 else "FAIL",
        command=command,
        returncode=completed.returncode,
        stdout_sha256=_digest(completed.stdout),
        stderr_sha256=_digest(completed.stderr),
        stdout_excerpt=_excerpt(completed.stdout),
        stderr_excerpt=_excerpt(completed.stderr),
    )


def _run_to_payload(result: ValidationRunResult) -> dict[str, Any]:
    return {
        "run_ref": result.run_ref,
        "status": result.status,
        "command": result.command,
        "returncode": result.returncode,
        "stdout_sha256": result.stdout_sha256,
        "stderr_sha256": result.stderr_sha256,
        "stdout_excerpt": result.stdout_excerpt,
        "stderr_excerpt": result.stderr_excerpt,
    }


def _build_rerun_comparison(profile: dict[str, Any], results: list[ValidationRunResult], *, executed: bool) -> dict[str, Any]:
    if not executed:
        return {
            "status": "PLANNED",
            "consistent": False,
            "reason": "validation command was not executed",
            "run_refs": [result.run_ref for result in results],
        }
    if any(result.status != "PASS" for result in results):
        return {
            "status": "FAIL",
            "consistent": False,
            "reason": "one or more reruns failed",
            "run_refs": [result.run_ref for result in results],
        }
    stdout_hashes = {result.stdout_sha256 for result in results}
    stderr_hashes = {result.stderr_sha256 for result in results}
    consistent = len(stdout_hashes) <= 1 and len(stderr_hashes) <= 1
    return {
        "status": "PASS" if consistent else "NEEDS_REVIEW",
        "consistent": consistent,
        "reason": "rerun stdout/stderr hashes match" if consistent else "rerun output hashes differ",
        "required_min_reruns": profile.get("min_reruns"),
        "run_refs": [result.run_ref for result in results],
        "stdout_sha256_values": sorted(stdout_hashes),
        "stderr_sha256_values": sorted(stderr_hashes),
    }


def _counter_value(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _build_forbidden_ops_summary(profile: dict[str, Any], ops_counter: Path | None) -> dict[str, Any]:
    forbidden = [str(item) for item in profile.get("forbidden_operations") or [] if str(item)]
    if ops_counter is None:
        return {
            "status": "UNKNOWN",
            "source_ref": "",
            "real_lake_read_count": None,
            "forbidden_operation_counts": {name: None for name in forbidden},
            "violations": [],
            "reason": "no operation counter file supplied",
        }
    data = _load_json(ops_counter)
    counts = {name: _counter_value(data, f"{name}_count") for name in forbidden}
    violations = [name for name, count in counts.items() if count > 0]
    return {
        "status": "FAIL" if violations else "PASS",
        "source_ref": ops_counter.as_posix(),
        "real_lake_read_count": _counter_value(data, "real_lake_read_count"),
        "forbidden_operation_counts": counts,
        "violations": violations,
        "reason": "forbidden operations observed" if violations else "no forbidden operations observed",
    }


def _build_admission_summary(admission_package: Path | None) -> dict[str, Any]:
    if admission_package is None:
        return {
            "status": "UNKNOWN",
            "source_ref": "",
            "paper_candidate": None,
            "reason": "no admission package supplied",
        }
    data = _load_json(admission_package)
    return {
        "status": str(data.get("package_status") or data.get("admission_package_status") or data.get("status") or "UNKNOWN"),
        "source_ref": admission_package.as_posix(),
        "paper_candidate": data.get("paper_candidate"),
        "reason": str(data.get("reason") or data.get("summary") or ""),
    }


def run_validation_task(
    *,
    project_root: Path,
    cr_id: str,
    profile_name: str,
    reruns: int,
    command: str,
    execute: bool,
    output_dir: Path | None = None,
    ops_counter: Path | None = None,
    admission_package: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    project_root = project_root.resolve()
    if profile_name not in PROFILE_CONTRACTS:
        raise ValueError(f"unknown validation profile: {profile_name}")
    profile = PROFILE_CONTRACTS[profile_name]
    min_reruns = int(profile.get("min_reruns") or 1)
    if reruns < min_reruns:
        raise ValueError(f"profile {profile_name} requires at least {min_reruns} reruns")
    if execute and not command.strip():
        raise ValueError("--execute requires --command")
    command_parts = _parse_command(command) if command.strip() else []
    created_at = now_utc()
    run_id = f"{_safe_id(cr_id)}-{_safe_id(profile_name)}-{created_at.replace(':', '').replace('+', 'Z')}"
    task_dir = (
        output_dir
        or (_resolve_runtime_ref(project_root, VALIDATION_ROOT_REL.as_posix()) / cr_id / run_id)
    ).resolve()
    task_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = task_dir / RUN_LEDGER_NAME
    _append_ledger(
        ledger_path,
        {
            "event_type": "validation_task_started",
            "event_id": f"{run_id}-started",
            "cr_id": cr_id,
            "profile": profile_name,
            "created_at": created_at,
            "execute": execute,
            "reruns": reruns,
        },
    )

    results: list[ValidationRunResult] = []
    for index in range(1, reruns + 1):
        run_ref = f"{run_id}-run-{index}"
        if execute:
            completed = _run_command(command_parts, cwd=project_root)
            result = _executed_run(run_ref, command_parts, completed)
            event_type = "validation_run_executed"
        else:
            result = _planned_run(run_ref, command_parts)
            event_type = "validation_run_planned"
        results.append(result)
        _append_ledger(
            ledger_path,
            {
                "event_type": event_type,
                "event_id": run_ref,
                "cr_id": cr_id,
                "profile": profile_name,
                "run": _run_to_payload(result),
                "created_at": now_utc(),
            },
        )

    rerun_comparison = _build_rerun_comparison(profile, results, executed=execute)
    forbidden_ops_summary = _build_forbidden_ops_summary(profile, ops_counter.resolve() if ops_counter else None)
    admission_summary = _build_admission_summary(admission_package.resolve() if admission_package else None)
    task_status = "PASS"
    if not execute:
        task_status = "PLANNED"
    if any(result.status == "FAIL" for result in results) or forbidden_ops_summary["status"] == "FAIL":
        task_status = "FAIL"
    elif rerun_comparison["status"] == "NEEDS_REVIEW" or admission_summary["status"] in {"FAIL", "BLOCKED"}:
        task_status = "NEEDS_REVIEW"

    rerun_ref = _write_json(project_root, task_dir / RERUN_COMPARISON_NAME, rerun_comparison)
    forbidden_ops_ref = _write_json(project_root, task_dir / FORBIDDEN_OPS_SUMMARY_NAME, forbidden_ops_summary)
    admission_ref = _write_json(project_root, task_dir / ADMISSION_SUMMARY_NAME, admission_summary)
    evidence_index = {
        "schema_version": 1,
        "kind": "validation-task-evidence-index",
        "cr_id": cr_id,
        "profile": profile_name,
        "run_id": run_id,
        "status": task_status,
        "created_at": created_at,
        "execute": execute,
        "required_evidence": profile.get("required_evidence"),
        "allowed_capabilities": profile.get("allowed_capabilities"),
        "forbidden_operations": profile.get("forbidden_operations"),
        "run_ledger_ref": _rel(project_root, ledger_path),
        "rerun_comparison_ref": rerun_ref,
        "forbidden_ops_summary_ref": forbidden_ops_ref,
        "admission_summary_ref": admission_ref,
        "runs": [_run_to_payload(result) for result in results],
    }
    evidence_ref = _write_json(project_root, task_dir / EVIDENCE_INDEX_NAME, evidence_index)
    latest_ref = _write_json(
        project_root,
        _resolve_runtime_ref(project_root, EVIDENCE_ROOT_REL.as_posix())
        / f"{cr_id}.{profile_name}.validation.index.json",
        {**evidence_index, "source_evidence_ref": evidence_ref},
    )
    _append_ledger(
        ledger_path,
        {
            "event_type": "validation_task_completed",
            "event_id": f"{run_id}-completed",
            "cr_id": cr_id,
            "profile": profile_name,
            "status": task_status,
            "evidence_ref": evidence_ref,
            "latest_evidence_ref": latest_ref,
            "created_at": now_utc(),
        },
    )
    return (0 if task_status in {"PASS", "PLANNED", "NEEDS_REVIEW"} else 1), evidence_index


def _print_help() -> None:
    print(
        "usage: meta-flow validation <command> [options]\n\n"
        "Commands:\n"
        "  run  Generate or execute a profile-driven validation task wrapper.\n\n"
        "Examples:\n"
        "  meta-flow validation run --cr CR-155 --profile real-lake-readonly --reruns 2 --project-root .\n"
        "  meta-flow validation run --cr CR-155 --profile real-lake-readonly --reruns 2 --command 'uv run python research/run.py' --execute --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return 0
    command_name = args[0]
    if command_name != "run":
        raise SystemExit(f"unknown validation command: {command_name}")
    parser = argparse.ArgumentParser(prog="meta-flow validation run")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--cr", dest="cr_id", required=True)
    parser.add_argument("--profile", default="real-lake-readonly")
    parser.add_argument("--reruns", type=int, default=2)
    parser.add_argument("--command", default="")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--ops-counter", type=Path, default=None)
    parser.add_argument("--admission-package", type=Path, default=None)
    parsed = parser.parse_args(args[1:])
    try:
        status, evidence = run_validation_task(
            project_root=parsed.project_root,
            cr_id=parsed.cr_id,
            profile_name=parsed.profile,
            reruns=parsed.reruns,
            command=parsed.command,
            execute=parsed.execute,
            output_dir=parsed.output_dir,
            ops_counter=parsed.ops_counter,
            admission_package=parsed.admission_package,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Validation Task: FAIL\n- ERROR: {exc}", file=sys.stderr)
        return 2
    print("Validation Task: " + str(evidence["status"]))
    print(f"evidence_ref: {evidence['run_ledger_ref'].rsplit('/', 1)[0]}/{EVIDENCE_INDEX_NAME}")
    print(f"latest_evidence_ref: {EVIDENCE_ROOT_REL.as_posix()}/{parsed.cr_id}.{parsed.profile}.validation.index.json")
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
