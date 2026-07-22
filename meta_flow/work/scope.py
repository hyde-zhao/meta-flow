"""Work deny-default 读、写与检查范围。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

_CHECK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _validate_path_pattern(pattern: str) -> None:
    prefix = pattern[:-3] if pattern.endswith("/**") else pattern
    path = Path(prefix)
    if (
        not pattern
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or ("*" in prefix or "?" in prefix or "[" in prefix)
    ):
        raise ValueError(f"unsafe scope path pattern: {pattern}")


def _normalize_requested_path(value: str) -> str:
    path = Path(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe requested path: {value}")
    return path.as_posix()


def _matches(pattern: str, requested: str) -> bool:
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return requested == prefix or requested.startswith(prefix + "/")
    return requested == pattern


@dataclass(frozen=True)
class WorkScope:
    version: int
    allowed_reads: tuple[str, ...]
    allowed_writes: tuple[str, ...]
    required_checks: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version < 1:
            raise ValueError("scope version must be >= 1")
        if not all(isinstance(items, tuple) for items in (
            self.allowed_reads,
            self.allowed_writes,
            self.required_checks,
        )):
            raise ValueError("scope collections must be tuples")
        for pattern in (*self.allowed_reads, *self.allowed_writes):
            _validate_path_pattern(pattern)
        if len(set(self.allowed_reads)) != len(self.allowed_reads):
            raise ValueError("allowed_reads contains duplicates")
        if len(set(self.allowed_writes)) != len(self.allowed_writes):
            raise ValueError("allowed_writes contains duplicates")
        if len(set(self.required_checks)) != len(self.required_checks):
            raise ValueError("required_checks contains duplicates")
        if not all(_CHECK_ID_RE.fullmatch(item) for item in self.required_checks):
            raise ValueError("required_checks contains unsafe check id")

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "allowed_reads": list(self.allowed_reads),
            "allowed_writes": list(self.allowed_writes),
            "required_checks": list(self.required_checks),
        }

    @property
    def digest(self) -> str:
        canonical = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ScopeDecision:
    decision: str
    operation: str
    requested: str
    matched_rule: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"


def exact_scope_difference(declared: tuple[str, ...], observed: tuple[str, ...]) -> dict[str, object]:
    """Compare two exact scope sets without allowing glob or prefix expansion."""

    declared_set = set(declared)
    observed_set = set(observed)
    missing = sorted(declared_set - observed_set)
    unexpected = sorted(observed_set - declared_set)
    return {
        "missing": missing,
        "unexpected": unexpected,
        "symmetric_difference_count": len(missing) + len(unexpected),
        "decision": "PASS" if not missing and not unexpected else "BLOCKED",
    }


def check_scope(scope: WorkScope, operation: str, requested: str) -> ScopeDecision:
    if operation == "read":
        normalized = _normalize_requested_path(requested)
        rules = scope.allowed_reads
    elif operation == "write":
        normalized = _normalize_requested_path(requested)
        rules = scope.allowed_writes
    elif operation == "check":
        if not _CHECK_ID_RE.fullmatch(requested):
            raise ValueError(f"unsafe requested check id: {requested}")
        normalized = requested
        rules = scope.required_checks
    else:
        raise ValueError("operation must be read, write, or check")

    for rule in rules:
        if operation == "check":
            matched = normalized == rule
        else:
            matched = _matches(rule, normalized)
        if matched:
            return ScopeDecision("ALLOW", operation, normalized, rule, "operation is declared in Work scope")
    return ScopeDecision("DENY", operation, normalized, "", "operation is outside deny-default Work scope")
