#!/usr/bin/env python3
"""在 frozen source 上生成不包含 wheel build 的 provider qualification receipt。"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.workflow.package_plan import canonical_digest

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_OPERATION_CLASSES = {"static-check", "provider-contract", "detector", "clean-source"}


def _closed(value: object, fields: set[str], *, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(code)
    return value


def _text(
    value: object,
    *,
    code: str,
    pattern: re.Pattern[str] | None = None,
    allow_empty: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or (not value and not allow_empty)
        or (pattern is not None and not pattern.fullmatch(value))
    ):
        raise ValueError(code)
    return value


def _strings(value: object, *, code: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item or item != item.strip() for item in value
    ):
        raise ValueError(code)
    return tuple(sorted(set(value)))


@dataclass(frozen=True)
class ProviderSourceCheckV1:
    check_id: str
    operation_class: str
    command_digest: str
    result_digest: str
    decision: str
    wheel_build_count: int

    @classmethod
    def from_mapping(cls, value: object) -> ProviderSourceCheckV1:
        item = _closed(
            value,
            {
                "check_id",
                "operation_class",
                "command_digest",
                "result_digest",
                "decision",
                "wheel_build_count",
            },
            code="PROVIDER_SOURCE_CHECK_FIELDS_MISMATCH",
        )
        operation_class = _text(
            item["operation_class"], code="PROVIDER_SOURCE_OPERATION_CLASS_INVALID"
        )
        if operation_class not in _OPERATION_CLASSES:
            raise ValueError("PROVIDER_SOURCE_OPERATION_CLASS_INVALID")
        decision = _text(item["decision"], code="PROVIDER_SOURCE_CHECK_DECISION_INVALID")
        if decision not in {"PASS", "BLOCKED", "CHECK_HARNESS_ERROR"}:
            raise ValueError("PROVIDER_SOURCE_CHECK_DECISION_INVALID")
        count = item["wheel_build_count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("PROVIDER_SOURCE_WHEEL_BUILD_COUNT_INVALID")
        return cls(
            check_id=_text(item["check_id"], code="PROVIDER_SOURCE_CHECK_ID_INVALID"),
            operation_class=operation_class,
            command_digest=_text(
                item["command_digest"], code="PROVIDER_SOURCE_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            result_digest=_text(
                item["result_digest"], code="PROVIDER_SOURCE_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            decision=decision,
            wheel_build_count=count,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "operation_class": self.operation_class,
            "command_digest": self.command_digest,
            "result_digest": self.result_digest,
            "decision": self.decision,
            "wheel_build_count": self.wheel_build_count,
        }


@dataclass(frozen=True)
class ProviderSourceQualificationInputV1:
    schema_version: int
    package_id: str
    cr_id: str
    version: str
    release_oid: str
    process_oid: str
    source_fingerprint: str
    plan_digest: str
    cost_digest: str
    compatibility_digest: str
    dirty_paths: tuple[str, ...]
    unresolved_harness_errors: int
    checks: tuple[ProviderSourceCheckV1, ...]
    execution_class: str
    authorization_ref: str
    authorization_digest: str

    @classmethod
    def from_mapping(cls, value: object) -> ProviderSourceQualificationInputV1:
        fields = {
            "schema_version",
            "package_id",
            "cr_id",
            "version",
            "release_oid",
            "process_oid",
            "source_fingerprint",
            "plan_digest",
            "cost_digest",
            "compatibility_digest",
            "dirty_paths",
            "unresolved_harness_errors",
            "checks",
            "execution_class",
            "authorization_ref",
            "authorization_digest",
        }
        item = _closed(value, fields, code="PROVIDER_SOURCE_INPUT_FIELDS_MISMATCH")
        if item["schema_version"] != 1:
            raise ValueError("PROVIDER_SOURCE_INPUT_SCHEMA_INVALID")
        execution_class = _text(
            item["execution_class"], code="PROVIDER_SOURCE_EXECUTION_CLASS_INVALID"
        )
        if execution_class not in {"fixture", "release-action"}:
            raise ValueError("PROVIDER_SOURCE_EXECUTION_CLASS_INVALID")
        harness_errors = item["unresolved_harness_errors"]
        if not isinstance(harness_errors, int) or isinstance(harness_errors, bool) or harness_errors < 0:
            raise ValueError("PROVIDER_SOURCE_HARNESS_COUNT_INVALID")
        if not isinstance(item["checks"], (list, tuple)) or not item["checks"]:
            raise ValueError("PROVIDER_SOURCE_CHECKS_INVALID")
        authorization_ref = _text(
            item["authorization_ref"], code="PROVIDER_SOURCE_AUTHORIZATION_INVALID", allow_empty=True
        )
        authorization_digest = _text(
            item["authorization_digest"],
            code="PROVIDER_SOURCE_AUTHORIZATION_INVALID",
            pattern=_DIGEST_RE if item["authorization_digest"] else None,
            allow_empty=True,
        )
        if execution_class == "release-action" and (
            not authorization_ref
            or not authorization_ref.startswith("process/")
            or not authorization_digest
        ):
            raise ValueError("PROVIDER_SOURCE_AUTHORIZATION_REQUIRED")
        return cls(
            schema_version=1,
            package_id=_text(item["package_id"], code="PROVIDER_SOURCE_PACKAGE_INVALID"),
            cr_id=_text(item["cr_id"], code="PROVIDER_SOURCE_CR_INVALID"),
            version=_text(item["version"], code="PROVIDER_SOURCE_VERSION_INVALID", pattern=_VERSION_RE),
            release_oid=_text(item["release_oid"], code="PROVIDER_SOURCE_OID_INVALID", pattern=_OID_RE),
            process_oid=_text(item["process_oid"], code="PROVIDER_SOURCE_OID_INVALID", pattern=_OID_RE),
            source_fingerprint=_text(
                item["source_fingerprint"], code="PROVIDER_SOURCE_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            plan_digest=_text(item["plan_digest"], code="PROVIDER_SOURCE_DIGEST_INVALID", pattern=_DIGEST_RE),
            cost_digest=_text(item["cost_digest"], code="PROVIDER_SOURCE_DIGEST_INVALID", pattern=_DIGEST_RE),
            compatibility_digest=_text(
                item["compatibility_digest"], code="PROVIDER_SOURCE_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            dirty_paths=_strings(item["dirty_paths"], code="PROVIDER_SOURCE_DIRTY_PATHS_INVALID"),
            unresolved_harness_errors=harness_errors,
            checks=tuple(
                sorted(
                    (ProviderSourceCheckV1.from_mapping(check) for check in item["checks"]),
                    key=lambda check: check.check_id,
                )
            ),
            execution_class=execution_class,
            authorization_ref=authorization_ref,
            authorization_digest=authorization_digest,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "cr_id": self.cr_id,
            "version": self.version,
            "release_oid": self.release_oid,
            "process_oid": self.process_oid,
            "source_fingerprint": self.source_fingerprint,
            "plan_digest": self.plan_digest,
            "cost_digest": self.cost_digest,
            "compatibility_digest": self.compatibility_digest,
            "dirty_paths": list(self.dirty_paths),
            "unresolved_harness_errors": self.unresolved_harness_errors,
            "checks": [check.as_dict() for check in self.checks],
            "execution_class": self.execution_class,
            "authorization_ref": self.authorization_ref,
            "authorization_digest": self.authorization_digest,
        }


def qualify_provider_source(value: ProviderSourceQualificationInputV1) -> dict[str, Any]:
    diagnostics: list[str] = []
    if value.dirty_paths:
        diagnostics.append("PROVIDER_SOURCE_DIRTY")
    if value.unresolved_harness_errors:
        diagnostics.append("CHECK_HARNESS_ERROR_UNRESOLVED")
    if any(check.wheel_build_count != 0 for check in value.checks):
        diagnostics.append("SOURCE_QUALIFICATION_HIDDEN_BUILD")
    if any(check.decision != "PASS" for check in value.checks):
        diagnostics.append("PROVIDER_SOURCE_CHECK_FAILED")
    authoritative = value.execution_class == "release-action" and not diagnostics
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": "ProviderSourceQualificationReceiptV1",
        "package_id": value.package_id,
        "cr_id": value.cr_id,
        "version": value.version,
        "release_oid": value.release_oid,
        "process_oid": value.process_oid,
        "source_fingerprint": value.source_fingerprint,
        "plan_digest": value.plan_digest,
        "cost_digest": value.cost_digest,
        "compatibility_digest": value.compatibility_digest,
        "input_digest": canonical_digest(value.as_dict()),
        "check_result_digests": [check.result_digest for check in value.checks],
        "execution_class": value.execution_class,
        "authorization_ref": value.authorization_ref,
        "authorization_digest": value.authorization_digest,
        "authoritative": authoritative,
        "wheel_build_count": 0,
        "qualification_increment": 1 if authoritative else 0,
        "diagnostics": sorted(set(diagnostics)),
        "decision": "BLOCKED" if diagnostics else "PASS",
        "mutation_count": 0,
    }
    payload["receipt_digest"] = canonical_digest(payload)
    return payload


def _regular_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError("PROVIDER_SOURCE_INPUT_NOT_REGULAR")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qualify_provider_source")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--format", choices=("json",), default="json")
    args = parser.parse_args(argv)
    try:
        value = ProviderSourceQualificationInputV1.from_mapping(_regular_json(args.input))
        result = qualify_provider_source(value)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": 1,
            "kind": "ProviderSourceQualificationFailureV1",
            "decision": "BLOCKED",
            "error_code": "CHECK_HARNESS_ERROR",
            "detail_code": str(exc).split(":", 1)[0],
            "wheel_build_count": 0,
            "qualification_increment": 0,
            "mutation_count": 0,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["decision"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
