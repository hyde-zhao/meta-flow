"""Linux ``uv tool`` 生命周期 executor 与只读 source diagnostics。"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from meta_flow.installation.authorization import ClaimedAuthorization
from meta_flow.installation.canonical import canonical_digest
from meta_flow.installation.contracts import (
    ContractErrorCode,
    InstallationContractError,
    validate_action,
)
from meta_flow.installation.engine import ExecutionOutcome
from meta_flow.installation.identity import (
    resolve_source_identity,
    validate_source_identity,
)

CLI_OPERATIONS = ("cli.install", "cli.upgrade", "cli.uninstall")
UV_DISTRIBUTION = "meta-flow"


class CliExecutionError(InstallationContractError):
    """CLI executor 的稳定 fail-closed 错误。"""


@dataclass(frozen=True)
class UvToolRequest:
    operation: str
    distribution: str
    source_argument: str
    source_identity: Mapping[str, str]
    force_refresh: bool = False


@dataclass(frozen=True)
class UvToolReceipt:
    returncode: int
    stdout: str
    stderr: str
    observed_identity: Mapping[str, str] | None


UvRunner = Callable[[Sequence[str]], UvToolReceipt]


@dataclass(frozen=True)
class CliExecutionContext:
    claimed: ClaimedAuthorization
    expected_plan_digest: str
    operation: str
    platform: str
    journal_prepared: bool
    source_identity: Mapping[str, str]
    source_argument: str
    runner: UvRunner


@dataclass(frozen=True)
class CliActionOutcome:
    action_id: str
    state: str
    error_code: str
    returncode: int
    mutation_count: int
    argv: tuple[str, ...]
    observed_identity: Mapping[str, str] | None

    def as_execution_outcome(self) -> ExecutionOutcome:
        return ExecutionOutcome(
            mutation_count=self.mutation_count,
            value={
                "action_id": self.action_id,
                "state": self.state,
                "error_code": self.error_code,
                "returncode": self.returncode,
                "argv": list(self.argv),
                "observed_identity": (
                    dict(self.observed_identity)
                    if self.observed_identity is not None
                    else None
                ),
            },
        )


def uv_tool_argv(request: UvToolRequest) -> tuple[str, ...]:
    """把受控 request 映射为结构化 argv；不使用 shell 或 Python fallback。"""

    if request.operation not in CLI_OPERATIONS:
        raise CliExecutionError(
            ContractErrorCode.INVALID_ENUM,
            f"unsupported CLI lifecycle operation: {request.operation}",
        )
    if request.distribution != UV_DISTRIBUTION:
        raise CliExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "CLI executor only owns the meta-flow distribution",
        )
    validate_source_identity(request.source_identity)
    if request.operation == "cli.uninstall":
        if request.force_refresh:
            raise CliExecutionError(
                ContractErrorCode.INVALID_ENUM,
                "cli.uninstall cannot force refresh",
            )
        return ("uv", "tool", "uninstall", request.distribution)
    if not request.source_argument or "\x00" in request.source_argument:
        raise CliExecutionError(
            ContractErrorCode.IDENTITY_INCOMPLETE,
            "CLI install/upgrade requires one source argument",
        )
    argv = ["uv", "tool", "install"]
    if request.operation == "cli.upgrade" or request.force_refresh:
        argv.append("--force")
    argv.extend(("--from", request.source_argument, request.distribution))
    return tuple(argv)


def invoke_uv_tool(
    request: UvToolRequest,
    *,
    runner: UvRunner | None = None,
) -> UvToolReceipt:
    """调用注入的或默认的结构化 uv runner。"""

    argv = uv_tool_argv(request)
    selected_runner = runner or _subprocess_uv_runner
    return selected_runner(argv)


def execute_cli_action(
    context: CliExecutionContext,
    action: object,
) -> CliActionOutcome:
    """执行一个已 claim、已 durable journal 的 ``invoke_uv_tool`` action。"""

    normalized = validate_action(action)
    _validate_context(context, normalized)
    desired_state = normalized["desired_state"]
    desired_identity = desired_state.get("source_identity")
    if not isinstance(desired_identity, Mapping):
        raise CliExecutionError(
            ContractErrorCode.MISSING_KEY,
            "CLI action desired_state requires source_identity",
        )
    try:
        exact_identity = resolve_source_identity(
            context.source_identity,
            desired_identity,
        )
    except InstallationContractError as exc:
        raise CliExecutionError(
            exc.code,
            str(exc).split(": ", 1)[-1],
        ) from exc
    force_refresh = desired_state.get("force_refresh", False)
    if not isinstance(force_refresh, bool):
        raise CliExecutionError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "CLI action force_refresh must be boolean",
        )
    request = UvToolRequest(
        operation=context.operation,
        distribution=UV_DISTRIBUTION,
        source_argument=context.source_argument,
        source_identity=exact_identity,
        force_refresh=force_refresh,
    )
    argv = uv_tool_argv(request)
    receipt = invoke_uv_tool(request, runner=context.runner)
    if receipt.returncode != 0:
        return CliActionOutcome(
            action_id=str(normalized["action_id"]),
            state="partial",
            error_code="UV_TOOL_FAILED",
            returncode=receipt.returncode,
            mutation_count=0,
            argv=argv,
            observed_identity=receipt.observed_identity,
        )
    if context.operation != "cli.uninstall":
        if receipt.observed_identity is None:
            return CliActionOutcome(
                action_id=str(normalized["action_id"]),
                state="partial",
                error_code="IDENTITY_INCOMPLETE",
                returncode=0,
                mutation_count=1,
                argv=argv,
                observed_identity=None,
            )
        try:
            resolve_source_identity(exact_identity, receipt.observed_identity)
        except InstallationContractError:
            return CliActionOutcome(
                action_id=str(normalized["action_id"]),
                state="partial",
                error_code="SOURCE_DRIFT",
                returncode=0,
                mutation_count=1,
                argv=argv,
                observed_identity=receipt.observed_identity,
            )
    return CliActionOutcome(
        action_id=str(normalized["action_id"]),
        state="applied",
        error_code="",
        returncode=0,
        mutation_count=1,
        argv=argv,
        observed_identity=receipt.observed_identity,
    )


def build_cli_diagnostics(
    identity: object,
    *,
    manifest_facts: Mapping[str, object] | None,
    receipt_facts: Mapping[str, object] | None,
) -> dict[str, object]:
    """生成稳定的只读 diagnostics；不完整或漂移事实永远 ``ready=false``。"""

    try:
        normalized = validate_source_identity(identity)
    except InstallationContractError as exc:
        return {
            "ready": False,
            "status": "IDENTITY_INCOMPLETE",
            "version": "",
            "source": "",
            "git_oid": "",
            "delivery_tree_digest": "",
            "findings": [exc.code.value],
        }
    findings: list[str] = []
    identity_digest = canonical_digest(normalized)
    if manifest_facts is None:
        findings.append("MANIFEST_MISSING")
    elif manifest_facts.get("source_identity_digest") != identity_digest:
        findings.append("MANIFEST_SOURCE_DRIFT")
    if receipt_facts is None:
        findings.append("RECEIPT_MISSING")
    elif receipt_facts.get("source_identity_digest") != identity_digest:
        findings.append("RECEIPT_SOURCE_DRIFT")
    elif receipt_facts.get("terminal") not in {"applied", "noop"}:
        findings.append("RECEIPT_NOT_TERMINAL")
    return {
        "ready": not findings,
        "status": "READY" if not findings else findings[0],
        "version": normalized["version"],
        "source": normalized["source"],
        "git_oid": normalized["oid"],
        "delivery_tree_digest": normalized["delivery_tree_digest"],
        "findings": findings,
    }


def normalize_reinstall(
    *,
    surface: str,
    selector: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """把 reinstall 规范化为单一 upgrade/force-refresh transaction。"""

    if surface not in {"cli", "assets"}:
        raise CliExecutionError(
            ContractErrorCode.INVALID_ENUM,
            "reinstall surface must be cli or assets",
        )
    normalized_selector = dict(selector or {})
    normalized_selector["force_refresh"] = True
    return {
        "operation": f"{surface}.upgrade",
        "selector": normalized_selector,
        "transaction_count": 1,
        "authorization_count": 1,
    }


def bootstrap_main(argv: Sequence[str] | None = None) -> int:
    """Source checkout 的最小安全入口；默认仅输出 dry-run request。"""

    parser = argparse.ArgumentParser(prog="install-cli.py")
    parser.add_argument(
        "operation",
        choices=("install", "upgrade", "uninstall", "reinstall"),
    )
    parser.add_argument("--source", default=".")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.operation == "reinstall":
        normalized = normalize_reinstall(surface="cli")
    else:
        normalized = {
            "operation": f"cli.{args.operation}",
            "selector": {"force_refresh": False},
            "transaction_count": 1,
            "authorization_count": 0 if args.dry_run else 1,
        }
    result = {
        **normalized,
        "decision": "READY" if args.dry_run else "BLOCKED",
        "mutation_count": 0,
        "source": args.source,
        "reason": "" if args.dry_run else "typed-authorization-required",
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if args.dry_run else 2


def _validate_context(
    context: CliExecutionContext,
    action: Mapping[str, Any],
) -> None:
    if not isinstance(context.claimed, ClaimedAuthorization):
        raise CliExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "CLI executor requires one claimed authorization context",
        )
    if context.claimed.plan_digest != context.expected_plan_digest:
        raise CliExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "claimed plan digest does not match CLI executor context",
        )
    if context.operation not in CLI_OPERATIONS:
        raise CliExecutionError(
            ContractErrorCode.INVALID_ENUM,
            "CLI executor only accepts cli.* operations",
        )
    if context.platform != "linux":
        raise CliExecutionError(
            ContractErrorCode.INVALID_ENUM,
            "CLI lifecycle currently supports Linux only",
        )
    if not context.journal_prepared:
        raise CliExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "durable journal/preimage must exist before uv mutation",
        )
    if (
        action["action_kind"] != "invoke_uv_tool"
        or action["component"] != "cli"
        or action["ownership_kind"] != "uv_tool"
    ):
        raise CliExecutionError(
            ContractErrorCode.INVALID_ENUM,
            "CLI executor requires one invoke_uv_tool/cli/uv_tool action",
        )
    if action["target_ref"] != "uv-tool/meta-flow":
        raise CliExecutionError(
            ContractErrorCode.UNSAFE_PATH,
            "CLI executor only owns uv-tool/meta-flow",
        )


def _subprocess_uv_runner(argv: Sequence[str]) -> UvToolReceipt:
    completed = subprocess.run(
        list(argv),
        check=False,
        capture_output=True,
        text=True,
    )
    return UvToolReceipt(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        observed_identity=None,
    )


__all__ = [
    "CLI_OPERATIONS",
    "UV_DISTRIBUTION",
    "CliActionOutcome",
    "CliExecutionContext",
    "CliExecutionError",
    "UvToolReceipt",
    "UvToolRequest",
    "bootstrap_main",
    "build_cli_diagnostics",
    "execute_cli_action",
    "invoke_uv_tool",
    "normalize_reinstall",
    "uv_tool_argv",
]
