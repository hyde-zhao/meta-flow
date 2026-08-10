"""vNext 单仓提交/推送 CLI。

默认 dry-run，apply 需要匹配计划的 typed authorization；远端 ref 不存在时，
push 计划以 ``expected_remote_oid=""`` 表达 create-only，并输出授权哨兵
``authorization_expected_oid=ABSENT``。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from meta_flow.project.scale import load_yaml_object
from meta_flow.repository.publisher import (
    PublicationContext,
    PublicationEvidence,
    RepositoryApplyError,
    RepositoryAuthorization,
    apply_commit,
    apply_push,
    plan_commit,
    plan_push,
)

PUBLIC_OPERATION_DECLARATIONS = (
    ("repository.commit", ("meta-flow", "repository", "commit")),
    ("repository.push", ("meta-flow", "repository", "push")),
)


def _publication_inputs(parsed: argparse.Namespace) -> dict[str, object]:
    if parsed.publication_context_ref:
        return {
            "publication_context": PublicationContext(
                project_root=parsed.project_root,
                context_ref=parsed.publication_context_ref,
            )
        }
    return {
        "publication_evidence": PublicationEvidence(
            project_root=parsed.project_root,
            evidence_ref=parsed.publication_evidence_ref,
        )
    }


def _add_publication_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--publication-evidence-ref")
    source.add_argument("--publication-context-ref")


def _authorization(path: Path) -> RepositoryAuthorization:
    payload = load_yaml_object(path)
    allowed = {
        "authorization_id",
        "operation",
        "project_id",
        "work_id",
        "repo_role",
        "plan_digest",
        "expected_oid",
        "expires_at",
        "single_use",
    }
    if set(payload) != allowed:
        raise ValueError("repository authorization contains missing or unknown fields")
    return RepositoryAuthorization(**payload)


def commit_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow repository commit")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--repo-role", choices=["release", "process"], required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--allowed-path", action="append", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--expected-head-oid", required=True)
    parser.add_argument("--authorization", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    _add_publication_arguments(parser)
    parsed = parser.parse_args(argv)
    try:
        plan = plan_commit(
            project_id=parsed.project_id,
            work_id=parsed.work_id,
            repo_role=parsed.repo_role,
            repo_root=parsed.repo_root,
            allowed_paths=parsed.allowed_path,
            message=parsed.message,
            expected_head_oid=parsed.expected_head_oid,
            **_publication_inputs(parsed),
        )
        if parsed.apply:
            if parsed.authorization is None:
                raise ValueError("--apply requires a typed --authorization file")
            receipt = apply_commit(plan, _authorization(parsed.authorization))
    except (OSError, TypeError, ValueError) as exc:
        payload: dict[str, Any] = {"decision": "BLOCKED", "error": str(exc)}
        if isinstance(exc, RepositoryApplyError):
            payload["decision"] = exc.receipt.decision
            payload["failure_receipt"] = {
                **exc.receipt.__dict__,
                "staged_paths": list(exc.receipt.staged_paths),
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    payload: dict[str, Any] = plan.as_dict()
    if parsed.apply:
        payload["receipt"] = {
            **receipt.__dict__,
            "committed_paths": list(receipt.committed_paths),
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not plan.blocked else 1


def push_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow repository push")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--repo-role", choices=["release", "process"], required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--ref", required=True)
    parser.add_argument("--expected-remote-oid", required=True)
    parser.add_argument("--authorization", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    _add_publication_arguments(parser)
    parsed = parser.parse_args(argv)
    try:
        plan = plan_push(
            project_id=parsed.project_id,
            work_id=parsed.work_id,
            repo_role=parsed.repo_role,
            repo_root=parsed.repo_root,
            remote=parsed.remote,
            ref=parsed.ref,
            expected_remote_oid=parsed.expected_remote_oid,
            **_publication_inputs(parsed),
        )
        if parsed.apply:
            if parsed.authorization is None:
                raise ValueError("--apply requires a typed --authorization file")
            receipt = apply_push(plan, _authorization(parsed.authorization))
    except (OSError, TypeError, ValueError) as exc:
        payload: dict[str, Any] = {"decision": "BLOCKED", "error": str(exc)}
        if isinstance(exc, RepositoryApplyError):
            payload["decision"] = exc.receipt.decision
            payload["failure_receipt"] = {
                **exc.receipt.__dict__,
                "staged_paths": list(exc.receipt.staged_paths),
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    payload: dict[str, Any] = plan.as_dict()
    if parsed.apply:
        payload["receipt"] = {**receipt.__dict__, "argv": list(receipt.argv)}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not plan.blocked else 1


def main(argv: list[str] | None = None) -> int:
    args = argv or []
    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: meta-flow repository <commit|push> [options]\n\n"
            "Each repository is planned and published independently. Commands are dry-run by default; "
            "--apply requires one exact-plan typed authorization. An absent remote ref is published "
            "create-only with expected_remote_oid='' and authorization expected_oid=ABSENT.\n"
        )
        return 0
    command, forwarded = args[0], args[1:]
    if command == "commit":
        return commit_main(forwarded)
    if command == "push":
        return push_main(forwarded)
    raise SystemExit("未知 repository 命令，目前支持: commit, push")
