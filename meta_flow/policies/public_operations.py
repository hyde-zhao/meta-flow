"""Validate the lightweight public operation contract registry."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.process_route import _resolve_runtime_path
from meta_flow.project.scale import load_yaml_object

DEFAULT_REGISTRY_REL = Path("delivery/doc/PUBLIC-OPERATION-CONTRACTS.yaml")
REGISTRY_FIELDS = {"schema_version", "kind", "operations"}
CONTRACT_FIELDS = {
    "operation",
    "entry",
    "input_version",
    "output_version",
    "mutation_mode",
    "authorization_mode",
    "projector",
    "l3_journey",
    "path_contract",
}
PATH_CONTRACT_FIELDS = {
    "binding_mode",
    "project_root_argument",
    "logical_process_arguments",
    "resolved_path_visibility",
    "persisted_process_ref_mode",
    "absolute_process_path_limit",
}
MUTATION_MODES = {
    "zero-write",
    "append-only-prevalidated",
    "dry-run-digest-apply",
    "dry-run-typed-apply",
    "explicit-output-file",
}
AUTHORIZATION_MODES = {
    "none",
    "policy-enum",
    "expected-plan-digest",
    "typed-user-confirmation",
}
PUBLIC_OPERATION_ENTRIES = {
    "cp.projection": ("meta-flow", "cp", "projection"),
    "event.append": ("meta-flow", "event", "append"),
    "story.project-cp6": ("meta-flow", "story", "project-cp6"),
    "context.read-log": ("meta-flow", "context", "read-log"),
    "cr.terminate": ("meta-flow", "cr", "terminate"),
    "cr.status-sync": ("meta-flow", "cr", "status-sync"),
    "cr.close": ("meta-flow", "cr", "close"),
    "cr.conflicts.proposed": ("meta-flow", "cr", "conflicts", "--proposed"),
    "public-operations.check": ("meta-flow", "cr", "public-operations-check"),
    "repository.commit": ("meta-flow", "repository", "commit"),
    "repository.push": ("meta-flow", "repository", "push"),
    "route.c0-cutover-plan": ("meta-flow", "route", "c0-cutover-plan"),
    "route.c0-cutover-apply": ("meta-flow", "route", "c0-cutover-apply"),
    "human-gate.ask-user": ("meta-flow", "ask-user", "human-gate"),
    "human-gate.check": ("meta-flow", "check", "human-gate"),
}
L3_JOURNEYS = {
    "L3-EVENT",
    "L3-STORY",
    "L3-CONTEXT",
    "L3-CR",
    "L3-REPOSITORY",
    "L3-HUMAN-GATE",
}


@dataclass(frozen=True)
class PublicOperationPathContractV1:
    """One public operation's binding and persisted-path boundary."""

    binding_mode: str
    project_root_argument: str
    logical_process_arguments: tuple[str, ...]
    resolved_path_visibility: str
    persisted_process_ref_mode: str
    absolute_process_path_limit: int

    @classmethod
    def from_dict(
        cls,
        operation: str,
        payload: dict[str, Any],
    ) -> PublicOperationPathContractV1:
        if set(payload) != PATH_CONTRACT_FIELDS:
            missing = sorted(PATH_CONTRACT_FIELDS - set(payload))
            extra = sorted(set(payload) - PATH_CONTRACT_FIELDS)
            raise ValueError(
                f"{operation} path contract fields mismatch: missing={missing}, extra={extra}"
            )
        raw_arguments = payload.get("logical_process_arguments")
        if (
            not isinstance(raw_arguments, list)
            or any(
                not isinstance(argument, str) or not argument.startswith("--")
                for argument in raw_arguments
            )
            or len(set(raw_arguments)) != len(raw_arguments)
        ):
            raise ValueError(f"{operation} logical_process_arguments must be unique CLI flags")
        contract = cls(
            binding_mode=str(payload["binding_mode"]),
            project_root_argument=str(payload["project_root_argument"]),
            logical_process_arguments=tuple(raw_arguments),
            resolved_path_visibility=str(payload["resolved_path_visibility"]),
            persisted_process_ref_mode=str(payload["persisted_process_ref_mode"]),
            absolute_process_path_limit=payload["absolute_process_path_limit"],
        )
        if contract.binding_mode not in {"required", "not-applicable"}:
            raise ValueError(f"{operation} has invalid binding_mode")
        if contract.project_root_argument != "--project-root":
            raise ValueError(f"{operation} project_root_argument must be --project-root")
        if type(contract.absolute_process_path_limit) is not int:
            raise ValueError(f"{operation} absolute_process_path_limit must be one integer")
        if contract.absolute_process_path_limit != 0:
            raise ValueError(f"{operation} absolute_process_path_limit must be 0")
        if contract.binding_mode == "required":
            if contract.resolved_path_visibility != "internal-only":
                raise ValueError(f"{operation} resolved_path_visibility must be internal-only")
            if contract.persisted_process_ref_mode != "logical-only":
                raise ValueError(f"{operation} persisted_process_ref_mode must be logical-only")
        elif (
            contract.logical_process_arguments
            or contract.resolved_path_visibility != "not-applicable"
            or contract.persisted_process_ref_mode != "not-applicable"
        ):
            raise ValueError(f"{operation} not-applicable binding cannot declare process refs")
        return contract

    def as_dict(self) -> dict[str, Any]:
        return {
            "binding_mode": self.binding_mode,
            "project_root_argument": self.project_root_argument,
            "logical_process_arguments": list(self.logical_process_arguments),
            "resolved_path_visibility": self.resolved_path_visibility,
            "persisted_process_ref_mode": self.persisted_process_ref_mode,
            "absolute_process_path_limit": self.absolute_process_path_limit,
        }


@dataclass(frozen=True)
class PublicOperationContractV2:
    """One public operation's frozen discovery and mutation contract."""

    operation: str
    entry: tuple[str, ...]
    input_version: str
    output_version: str
    mutation_mode: str
    authorization_mode: str
    projector: str
    l3_journey: str
    path_contract: PublicOperationPathContractV1

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PublicOperationContractV2:
        if set(payload) != CONTRACT_FIELDS:
            missing = sorted(CONTRACT_FIELDS - set(payload))
            extra = sorted(set(payload) - CONTRACT_FIELDS)
            raise ValueError(f"public operation fields mismatch: missing={missing}, extra={extra}")
        entry = payload.get("entry")
        if (
            not isinstance(entry, list)
            or not entry
            or any(not isinstance(item, str) or not item for item in entry)
        ):
            raise ValueError("public operation entry must be a non-empty string list")
        contract = cls(
            operation=str(payload["operation"]),
            entry=tuple(entry),
            input_version=str(payload["input_version"]),
            output_version=str(payload["output_version"]),
            mutation_mode=str(payload["mutation_mode"]),
            authorization_mode=str(payload["authorization_mode"]),
            projector=str(payload["projector"]),
            l3_journey=str(payload["l3_journey"]),
            path_contract=PublicOperationPathContractV1.from_dict(
                str(payload["operation"]),
                dict(payload["path_contract"])
                if isinstance(payload["path_contract"], dict)
                else {},
            ),
        )
        if not contract.operation:
            raise ValueError("public operation id must be non-empty")
        if contract.entry[0] != "meta-flow":
            raise ValueError(f"{contract.operation} entry must start with meta-flow")
        if contract.mutation_mode not in MUTATION_MODES:
            raise ValueError(
                f"{contract.operation} has invalid mutation_mode: {contract.mutation_mode}"
            )
        if contract.authorization_mode not in AUTHORIZATION_MODES:
            raise ValueError(
                f"{contract.operation} has invalid authorization_mode: "
                f"{contract.authorization_mode}"
            )
        if not contract.input_version or not contract.output_version:
            raise ValueError(f"{contract.operation} input/output versions must be non-empty")
        if "." not in contract.projector:
            raise ValueError(f"{contract.operation} projector must be module-qualified")
        if contract.l3_journey not in L3_JOURNEYS:
            raise ValueError(f"{contract.operation} has invalid l3_journey: {contract.l3_journey}")
        return contract

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "entry": list(self.entry),
            "input_version": self.input_version,
            "output_version": self.output_version,
            "mutation_mode": self.mutation_mode,
            "authorization_mode": self.authorization_mode,
            "projector": self.projector,
            "l3_journey": self.l3_journey,
            "path_contract": self.path_contract.as_dict(),
        }


def load_public_operation_registry(
    project_root: Path,
    *,
    registry_path: Path = DEFAULT_REGISTRY_REL,
) -> tuple[PublicOperationContractV2, ...]:
    """Load a strict registry without importing or executing registered projectors."""

    root = project_root.resolve()
    if registry_path.is_absolute() or ".." in registry_path.parts:
        raise ValueError("registry path must be release-root-relative")
    path = _resolve_runtime_path(root, registry_path)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("registry path must remain inside release root") from exc
    if not path.is_file():
        raise ValueError(f"public operation registry missing: {registry_path.as_posix()}")
    payload = load_yaml_object(path)
    if set(payload) != REGISTRY_FIELDS:
        missing = sorted(REGISTRY_FIELDS - set(payload))
        extra = sorted(set(payload) - REGISTRY_FIELDS)
        raise ValueError(
            f"public operation registry fields mismatch: missing={missing}, extra={extra}"
        )
    if payload.get("schema_version") != 2:
        raise ValueError("public operation registry schema_version must be 2")
    if payload.get("kind") != "PublicOperationContractRegistryV2":
        raise ValueError("public operation registry kind mismatch")
    raw_operations = payload.get("operations")
    if not isinstance(raw_operations, list) or not raw_operations:
        raise ValueError("public operation registry operations must be non-empty")
    contracts = tuple(
        PublicOperationContractV2.from_dict(dict(item))
        for item in raw_operations
        if isinstance(item, dict)
    )
    if len(contracts) != len(raw_operations):
        raise ValueError("public operation registry entries must be objects")
    operation_ids = [contract.operation for contract in contracts]
    if len(set(operation_ids)) != len(operation_ids):
        raise ValueError("public operation registry contains duplicate operation ids")
    return contracts


def validate_public_operations(
    project_root: Path,
    *,
    registry_path: Path = DEFAULT_REGISTRY_REL,
    check_console: bool = True,
) -> dict[str, Any]:
    """Compare registry truth with the frozen public command inventory."""

    errors: list[str] = []
    console_results: list[dict[str, Any]] = []
    try:
        contracts = load_public_operation_registry(
            project_root,
            registry_path=registry_path,
        )
    except (OSError, ValueError) as exc:
        return {
            "schema_version": 2,
            "kind": "PublicOperationRegistryCheckV2",
            "decision": "FAIL",
            "documented_operation_count": 0,
            "undocumented_public_operations": sorted(PUBLIC_OPERATION_ENTRIES),
            "unknown_registry_operations": [],
            "l3_journey_count": 0,
            "console_results": [],
            "errors": [str(exc)],
        }
    by_id = {contract.operation: contract for contract in contracts}
    undocumented = sorted(set(PUBLIC_OPERATION_ENTRIES) - set(by_id))
    unknown = sorted(set(by_id) - set(PUBLIC_OPERATION_ENTRIES))
    if undocumented:
        errors.append("undocumented public operations: " + ", ".join(undocumented))
    if unknown:
        errors.append("unknown registry operations: " + ", ".join(unknown))
    for operation, expected_entry in PUBLIC_OPERATION_ENTRIES.items():
        contract = by_id.get(operation)
        if contract is not None and contract.entry != expected_entry:
            errors.append(
                f"{operation} entry mismatch: "
                f"expected={list(expected_entry)} actual={list(contract.entry)}"
            )
    if check_console:
        console = Path(sys.executable).with_name("meta-flow")
        if not console.is_file():
            errors.append("meta-flow console entry is not discoverable")
        else:
            for contract in contracts:
                completed = subprocess.run(
                    [str(console), *contract.entry[1:], "--help"],
                    cwd=project_root.resolve(),
                    check=False,
                    capture_output=True,
                    text=True,
                )
                console_results.append(
                    {
                        "operation": contract.operation,
                        "entry": list(contract.entry),
                        "exit_code": completed.returncode,
                        "discovered": completed.returncode == 0,
                    }
                )
                if completed.returncode != 0:
                    errors.append(f"{contract.operation} public entry is not executable")
                elif (
                    contract.path_contract.binding_mode == "required"
                    and contract.path_contract.project_root_argument
                    not in completed.stdout + completed.stderr
                ):
                    errors.append(
                        f"{contract.operation} public entry does not expose "
                        f"{contract.path_contract.project_root_argument}"
                    )
                else:
                    help_text = completed.stdout + completed.stderr
                    for argument in contract.path_contract.logical_process_arguments:
                        if argument not in help_text:
                            errors.append(
                                f"{contract.operation} public entry does not expose "
                                f"declared logical process argument {argument}"
                            )
    return {
        "schema_version": 2,
        "kind": "PublicOperationRegistryCheckV2",
        "decision": "PASS" if not errors else "FAIL",
        "documented_operation_count": len(contracts),
        "undocumented_public_operations": undocumented,
        "unknown_registry_operations": unknown,
        "l3_journey_count": len({contract.l3_journey for contract in contracts}),
        "console_results": console_results,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow cr public-operations-check")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_REL)
    parser.add_argument("--skip-console", action="store_true")
    parsed = parser.parse_args(argv)
    result = validate_public_operations(
        parsed.project_root,
        registry_path=parsed.registry,
        check_console=not parsed.skip_console,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["decision"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
