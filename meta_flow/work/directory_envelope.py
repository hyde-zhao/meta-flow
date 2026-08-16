"""Closed, side-effect-free directory write envelope matching.

This module deliberately consumes facts captured by a caller.  An admission is
only a matcher decision: it never grants write authority and always reports a
zero mutation count.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum


class MatcherOp(StrEnum):
    EXACT_DIR = "EXACT_DIR"
    EXACT_LEAF = "EXACT_LEAF"
    ASCII_BASENAME_PREFIX = "ASCII_BASENAME_PREFIX"
    ASCII_BASENAME_SUFFIX = "ASCII_BASENAME_SUFFIX"
    ALL_OF = "ALL_OF"
    ANY_OF = "ANY_OF"


class ObjectClass(StrEnum):
    REGULAR_EXISTING = "REGULAR_EXISTING"
    APPROVED_MISSING_LEAF = "APPROVED_MISSING_LEAF"
    SYMLINK = "SYMLINK"
    IGNORED = "IGNORED"
    SUBMODULE = "SUBMODULE"
    OUTSIDE = "OUTSIDE"
    DUPLICATE_LOGICAL_OWNER = "DUPLICATE_LOGICAL_OWNER"
    MISSING_PARENT = "MISSING_PARENT"
    PARENT_TYPE_CONFLICT = "PARENT_TYPE_CONFLICT"
    UNKNOWN = "UNKNOWN"


class MatchReasonCode(StrEnum):
    ADMITTED = "ADMITTED"
    NON_RELATIVE = "NON_RELATIVE"
    EMPTY_SEGMENT = "EMPTY_SEGMENT"
    PARENT_SEGMENT = "PARENT_SEGMENT"
    BACKSLASH = "BACKSLASH"
    NON_ASCII = "NON_ASCII"
    CASE_OR_UNICODE_VARIANT = "CASE_OR_UNICODE_VARIANT"
    PREFIX_COLLISION = "PREFIX_COLLISION"
    UNDECLARED_DOTFILE = "UNDECLARED_DOTFILE"
    OBJECT_FORBIDDEN = "OBJECT_FORBIDDEN"
    OWNER_MISMATCH = "OWNER_MISMATCH"
    WAVE_MISMATCH = "WAVE_MISMATCH"
    MERGE_ORDER_MISMATCH = "MERGE_ORDER_MISMATCH"
    EXCLUSION_MATCH = "EXCLUSION_MATCH"
    ENVELOPE_DIGEST_MISMATCH = "ENVELOPE_DIGEST_MISMATCH"
    PREIMAGE_MISSING = "PREIMAGE_MISSING"
    PREIMAGE_DRIFT = "PREIMAGE_DRIFT"
    OID_DRIFT = "OID_DRIFT"
    AST_INVALID = "AST_INVALID"
    NO_PATTERN_MATCH = "NO_PATTERN_MATCH"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    FALLBACK_EXACT_LEAF_ONLY = "FALLBACK_EXACT_LEAF_ONLY"


class MatcherParseError(ValueError):
    """Typed closed-AST parse denial."""


class PathNormalizationError(ValueError):
    def __init__(self, reason: MatchReasonCode) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True)
class MatcherNode:
    op: MatcherOp
    value: str = ""
    directory: str = ""
    rules: tuple[MatcherNode, ...] = ()

    def as_dict(self) -> dict[str, object]:
        if self.op in {MatcherOp.ALL_OF, MatcherOp.ANY_OF}:
            return {"op": self.op.value, "rules": [rule.as_dict() for rule in self.rules]}
        result: dict[str, object] = {"op": self.op.value, "value": self.value}
        if self.op in {MatcherOp.ASCII_BASENAME_PREFIX, MatcherOp.ASCII_BASENAME_SUFFIX}:
            result["dir"] = self.directory
        return result


@dataclass(frozen=True)
class PathFactsV1:
    path: str
    object_class: ObjectClass = ObjectClass.UNKNOWN
    parent_safe: bool = False
    repository_contained: bool = False
    ignored: bool = False
    submodule: bool = False
    logical_owner_count: int = 0
    expected_preimage_digest: str | None = None
    current_preimage_digest: str | None = None


@dataclass(frozen=True)
class PlanApplyBindingV1:
    matcher_digest: str
    envelope_digest: str
    release_oid: str
    process_oid: str
    target_preimages: tuple[tuple[str, str], ...] = ()

    def preimages(self) -> dict[str, str]:
        return dict(self.target_preimages)


@dataclass(frozen=True)
class EnvelopeDecisionV1:
    admitted: bool
    reason_code: MatchReasonCode
    envelope_digest: str
    matcher_digest: str
    object_class: ObjectClass
    mutation_count: int = 0
    fallback_mode: bool = False
    release_oid: str = ""
    process_oid: str = ""


@dataclass(frozen=True)
class DirectoryWriteEnvelopeV1:
    owner_story_id: str
    wave_id: str
    merge_order: int
    exact_dirs: tuple[str, ...]
    matcher: MatcherNode
    exclusions: tuple[str, ...] = ()
    explicit_dotfiles: tuple[str, ...] = ()
    fallback_exact_leaves: tuple[str, ...] = ()
    schema_version: int = 1
    matcher_semantic_version: str = "DirectoryWriteEnvelopeV1"
    fallback_mode: bool = False

    def __post_init__(self) -> None:
        if not self.owner_story_id or not self.wave_id or self.merge_order < 0:
            raise ValueError("owner, wave, and non-negative merge order are required")
        object.__setattr__(self, "exact_dirs", _canonical_set(self.exact_dirs, directory=True))
        object.__setattr__(self, "exclusions", _canonical_set(self.exclusions))
        object.__setattr__(self, "explicit_dotfiles", _canonical_set(self.explicit_dotfiles))
        object.__setattr__(self, "fallback_exact_leaves", _canonical_set(self.fallback_exact_leaves))
        _validate_node(self.matcher)

    @property
    def digest(self) -> str:
        return envelope_digest(self)


def normalize_repo_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise PathNormalizationError(MatchReasonCode.NON_RELATIVE)
    if value.startswith("/") or value.startswith("~") or (len(value) > 1 and value[1] == ":"):
        raise PathNormalizationError(MatchReasonCode.NON_RELATIVE)
    if "\\" in value:
        raise PathNormalizationError(MatchReasonCode.BACKSLASH)
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise PathNormalizationError(MatchReasonCode.NON_ASCII) from exc
    segments = value.split("/")
    if any(segment == "" for segment in segments):
        raise PathNormalizationError(MatchReasonCode.EMPTY_SEGMENT)
    if any(segment in {".", ".."} for segment in segments):
        raise PathNormalizationError(MatchReasonCode.PARENT_SEGMENT)
    return value


def _canonical_set(values: Sequence[str], *, directory: bool = False) -> tuple[str, ...]:
    canonical: list[str] = []
    for value in values:
        normalized = normalize_repo_path(value)
        if directory and normalized.endswith("/"):
            raise ValueError("directory must not have a trailing separator")
        canonical.append(normalized)
    if len(canonical) != len(set(canonical)):
        raise ValueError("duplicate canonical path")
    return tuple(sorted(canonical))


def parse_matcher_ast(payload: Mapping[str, object]) -> MatcherNode:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("op"), str):
        raise MatcherParseError(MatchReasonCode.AST_INVALID.value)
    try:
        op = MatcherOp(payload["op"])
    except ValueError as exc:
        raise MatcherParseError(MatchReasonCode.AST_INVALID.value) from exc
    if op in {MatcherOp.ALL_OF, MatcherOp.ANY_OF}:
        if set(payload) != {"op", "rules"} or not isinstance(payload["rules"], list):
            raise MatcherParseError(MatchReasonCode.AST_INVALID.value)
        rules = tuple(parse_matcher_ast(item) for item in payload["rules"] if isinstance(item, Mapping))
        if len(rules) != len(payload["rules"]) or not rules:
            raise MatcherParseError(MatchReasonCode.AST_INVALID.value)
        node = MatcherNode(op=op, rules=rules)
    elif op == MatcherOp.EXACT_DIR:
        if set(payload) != {"op", "value"} or not isinstance(payload["value"], str):
            raise MatcherParseError(MatchReasonCode.AST_INVALID.value)
        node = MatcherNode(op=op, value=normalize_repo_path(payload["value"]))
    elif op == MatcherOp.EXACT_LEAF:
        if set(payload) != {"op", "value"} or not isinstance(payload["value"], str):
            raise MatcherParseError(MatchReasonCode.AST_INVALID.value)
        node = MatcherNode(op=op, value=normalize_repo_path(payload["value"]))
    else:
        if set(payload) != {"op", "dir", "value"} or not all(isinstance(payload[key], str) for key in ("dir", "value")):
            raise MatcherParseError(MatchReasonCode.AST_INVALID.value)
        directory = normalize_repo_path(str(payload["dir"]))
        value = str(payload["value"])
        if not value or "/" in value or "\\" in value or not value.isascii() or value.startswith("."):
            raise MatcherParseError(MatchReasonCode.AST_INVALID.value)
        node = MatcherNode(op=op, directory=directory, value=value)
    _validate_node(node)
    return node


def _wildcards(node: MatcherNode) -> int:
    if node.op in {MatcherOp.ASCII_BASENAME_PREFIX, MatcherOp.ASCII_BASENAME_SUFFIX}:
        return 1
    return sum(_wildcards(rule) for rule in node.rules)


def _validate_node(node: MatcherNode) -> None:
    if node.op in {MatcherOp.ALL_OF, MatcherOp.ANY_OF}:
        if not node.rules or len({json.dumps(rule.as_dict(), sort_keys=True) for rule in node.rules}) != len(node.rules):
            raise MatcherParseError(MatchReasonCode.AST_INVALID.value)
        for rule in node.rules:
            _validate_node(rule)
        if node.op == MatcherOp.ALL_OF and _wildcards(node) > 1:
            raise MatcherParseError(MatchReasonCode.AST_INVALID.value)
    elif node.op == MatcherOp.EXACT_DIR:
        normalize_repo_path(node.value)
    elif node.op == MatcherOp.EXACT_LEAF:
        normalize_repo_path(node.value)
    elif node.op in {MatcherOp.ASCII_BASENAME_PREFIX, MatcherOp.ASCII_BASENAME_SUFFIX}:
        normalize_repo_path(node.directory)
        if not node.value or "/" in node.value or not node.value.isascii():
            raise MatcherParseError(MatchReasonCode.AST_INVALID.value)
    else:
        raise MatcherParseError(MatchReasonCode.AST_INVALID.value)


def classify_object(path: str, facts: PathFactsV1) -> ObjectClass:
    if facts.path != path or not facts.repository_contained or facts.logical_owner_count != 1:
        return ObjectClass.UNKNOWN if facts.logical_owner_count == 0 else ObjectClass.DUPLICATE_LOGICAL_OWNER
    if facts.ignored:
        return ObjectClass.IGNORED
    if facts.submodule:
        return ObjectClass.SUBMODULE
    if facts.object_class == ObjectClass.APPROVED_MISSING_LEAF and not facts.parent_safe:
        return ObjectClass.MISSING_PARENT
    return facts.object_class


def envelope_digest(envelope: DirectoryWriteEnvelopeV1) -> str:
    payload = {
        "schema_version": envelope.schema_version,
        "owner_story_id": envelope.owner_story_id,
        "wave_id": envelope.wave_id,
        "merge_order": envelope.merge_order,
        "exact_dirs": envelope.exact_dirs,
        "matcher": envelope.matcher.as_dict(),
        "exclusions": envelope.exclusions,
        "explicit_dotfiles": envelope.explicit_dotfiles,
        "fallback_exact_leaves": envelope.fallback_exact_leaves,
        "matcher_semantic_version": envelope.matcher_semantic_version,
        "fallback_mode": envelope.fallback_mode,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _matches(node: MatcherNode, path: str) -> bool:
    directory, _, basename = path.rpartition("/")
    if node.op == MatcherOp.EXACT_DIR:
        return directory == node.value
    if node.op == MatcherOp.EXACT_LEAF:
        return path == node.value
    if node.op == MatcherOp.ASCII_BASENAME_PREFIX:
        return directory == node.directory and basename.startswith(node.value) and basename != node.value
    if node.op == MatcherOp.ASCII_BASENAME_SUFFIX:
        return directory == node.directory and basename.endswith(node.value) and basename != node.value
    if node.op == MatcherOp.ALL_OF:
        return all(_matches(rule, path) for rule in node.rules)
    return any(_matches(rule, path) for rule in node.rules)


def _decision(
    envelope: DirectoryWriteEnvelopeV1,
    reason: MatchReasonCode,
    object_class: ObjectClass = ObjectClass.UNKNOWN,
    *,
    admitted: bool = False,
    binding: PlanApplyBindingV1 | None = None,
) -> EnvelopeDecisionV1:
    return EnvelopeDecisionV1(
        admitted,
        reason,
        envelope.digest,
        envelope.digest,
        object_class,
        fallback_mode=envelope.fallback_mode,
        release_oid="" if binding is None else binding.release_oid,
        process_oid="" if binding is None else binding.process_oid,
    )


def match_write_envelope(
    envelope: DirectoryWriteEnvelopeV1,
    path: str,
    story_id: str,
    wave_id: str,
    facts: PathFactsV1,
    binding: PlanApplyBindingV1 | None = None,
    *,
    merge_order: int | None = None,
) -> EnvelopeDecisionV1:
    try:
        normalized = normalize_repo_path(path)
    except PathNormalizationError as exc:
        return _decision(envelope, exc.reason)
    object_class = classify_object(normalized, facts)
    if object_class not in {ObjectClass.REGULAR_EXISTING, ObjectClass.APPROVED_MISSING_LEAF}:
        return _decision(envelope, MatchReasonCode.OBJECT_FORBIDDEN, object_class)
    if story_id != envelope.owner_story_id:
        return _decision(envelope, MatchReasonCode.OWNER_MISMATCH, object_class)
    if wave_id != envelope.wave_id:
        return _decision(envelope, MatchReasonCode.WAVE_MISMATCH, object_class)
    if merge_order is not None and merge_order != envelope.merge_order:
        return _decision(envelope, MatchReasonCode.MERGE_ORDER_MISMATCH, object_class)
    if normalized in envelope.exclusions or any(normalized.startswith(f"{item}/") for item in envelope.exclusions):
        return _decision(envelope, MatchReasonCode.EXCLUSION_MATCH, object_class)
    exact_leaf = _matches_exact_leaf(envelope.matcher, normalized)
    if not exact_leaf and not any(normalized.startswith(f"{directory}/") for directory in envelope.exact_dirs):
        return _decision(envelope, MatchReasonCode.NO_PATTERN_MATCH, object_class)
    basename = normalized.rsplit("/", 1)[-1]
    if basename.startswith(".") and normalized not in envelope.explicit_dotfiles:
        return _decision(envelope, MatchReasonCode.UNDECLARED_DOTFILE, object_class)
    if binding is not None:
        if binding.envelope_digest != envelope.digest or binding.matcher_digest != envelope.digest:
            return _decision(envelope, MatchReasonCode.ENVELOPE_DIGEST_MISMATCH, object_class, binding=binding)
        expected = binding.preimages().get(normalized)
        if expected is None or facts.expected_preimage_digest is None or facts.current_preimage_digest is None:
            return _decision(envelope, MatchReasonCode.PREIMAGE_MISSING, object_class, binding=binding)
        if expected != facts.expected_preimage_digest or expected != facts.current_preimage_digest:
            return _decision(envelope, MatchReasonCode.PREIMAGE_DRIFT, object_class, binding=binding)
    matched = normalized in envelope.fallback_exact_leaves if envelope.fallback_mode else _matches(envelope.matcher, normalized)
    if not matched:
        return _decision(envelope, MatchReasonCode.NO_PATTERN_MATCH, object_class, binding=binding)
    return _decision(envelope, MatchReasonCode.ADMITTED, object_class, admitted=True, binding=binding)


def _matches_exact_leaf(node: MatcherNode, path: str) -> bool:
    if node.op == MatcherOp.EXACT_LEAF:
        return node.value == path
    if node.op in {MatcherOp.ALL_OF, MatcherOp.ANY_OF}:
        return any(_matches_exact_leaf(rule, path) for rule in node.rules)
    return False


def assert_plan_apply_semantics(plan: EnvelopeDecisionV1, apply: EnvelopeDecisionV1) -> EnvelopeDecisionV1:
    if (
        not plan.admitted
        or not apply.admitted
        or plan.matcher_digest != apply.matcher_digest
        or plan.envelope_digest != apply.envelope_digest
        or plan.release_oid != apply.release_oid
        or plan.process_oid != apply.process_oid
    ):
        return replace(apply, admitted=False, reason_code=MatchReasonCode.REPLAN_REQUIRED, mutation_count=0)
    return apply


def select_fallback(envelope: DirectoryWriteEnvelopeV1, corpus_receipt: Mapping[str, object]) -> DirectoryWriteEnvelopeV1:
    complete = corpus_receipt.get("complete") is True
    false_admits = corpus_receipt.get("false_admit_count")
    if complete and isinstance(false_admits, int) and false_admits == 0:
        return envelope
    return replace(envelope, fallback_mode=True)
