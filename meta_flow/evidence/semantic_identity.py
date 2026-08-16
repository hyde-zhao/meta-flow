"""Closed semantic identities bound to the approved CR-071 Bundle-C table."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from typing import Any

APPROVED_TABLE_DIGEST = "2ea864079b8c97ab2e3a02736313a8b1ca2610dbd4d848f8f731e6472bf3ccbf"
APPROVED_CANONICALIZER_SET_DIGEST = (
    "32ac368e6bbc7b8173213c26069ba492298327a0393c5f98be365647af068a41"
)
APPROVED_DIMENSIONS = (
    "source",
    "profile",
    "command",
    "environment",
    "runner",
    "evidence",
    "provenance",
)
_TABLE_RESOURCE = "concrete_equivalence_table_v1.json"
_REJECTED_DIMENSIONS = frozenset({"check", "dependency", "runtime"})
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_ROW_KEYS = {
    "dimension",
    "class_id",
    "canonicalizer_id",
    "canonical_input_fields",
    "equivalent_rule",
    "non_equivalent_boundaries",
    "safe_drift",
    "unknown_conditions",
    "counterexample_ids",
    "metamorphic_ids",
}


class EquivalenceDimensionV1(StrEnum):
    SOURCE = "source"
    PROFILE = "profile"
    COMMAND = "command"
    ENVIRONMENT = "environment"
    RUNNER = "runner"
    EVIDENCE = "evidence"
    PROVENANCE = "provenance"


class DimensionClassificationV1(StrEnum):
    EQUIVALENT = "EQUIVALENT"
    NON_EQUIVALENT = "NON_EQUIVALENT"
    UNKNOWN = "UNKNOWN"


class IdentityReasonV1(StrEnum):
    EQUIVALENT = "EQUIVALENT"
    NON_EQUIVALENT = "NON_EQUIVALENT"
    UNKNOWN_DIMENSION = "UNKNOWN_DIMENSION"
    MISSING_INPUT = "MISSING_INPUT"
    UNSUPPORTED_INPUT = "UNSUPPORTED_INPUT"
    CANONICALIZER_ERROR = "CANONICALIZER_ERROR"
    STALE_TABLE = "STALE_TABLE"


_FIELDS: dict[EquivalenceDimensionV1, tuple[str, ...]] = {
    EquivalenceDimensionV1.SOURCE: (
        "repo_role",
        "logical_refs_posix_byte_sorted",
        "content_digests",
        "generated_input_lineage_digest",
    ),
    EquivalenceDimensionV1.PROFILE: (
        "profile_schema_revision",
        "required_layers_ordered",
        "risk_class",
        "scope_digest",
        "policy_revision",
    ),
    EquivalenceDimensionV1.COMMAND: (
        "executable_identity_version",
        "subcommand",
        "normalized_flags",
        "explicit_defaults",
        "cwd_logical_role_scope",
        "stdin_contract",
    ),
    EquivalenceDimensionV1.ENVIRONMENT: (
        "platform",
        "architecture",
        "runtime_version",
        "locale_timezone_semantics",
        "declared_env_allowlist_value_digests",
        "capability_digest",
        "isolation_permission_network_policy_digest",
    ),
    EquivalenceDimensionV1.RUNNER: (
        "runner_checker_canonical_id",
        "implementation_digest",
        "invocation_schema",
        "selected_assertions",
        "failure_threshold",
        "orchestration_policy_digest",
    ),
    EquivalenceDimensionV1.EVIDENCE: (
        "required_evidence_schema",
        "validation_layers_ordered",
        "artifact_result_receipt_semantic_digests",
        "scenario_fixture_coverage",
        "sufficiency_decision",
    ),
    EquivalenceDimensionV1.PROVENANCE: (
        "producer_revision_lineage",
        "resolution_graph_digest",
        "fixture_data_lineage",
        "external_contract_digest",
    ),
}
_SORTED_SEQUENCE_FIELDS = frozenset(
    {
        "logical_refs_posix_byte_sorted",
        "content_digests",
        "normalized_flags",
        "explicit_defaults",
        "declared_env_allowlist_value_digests",
        "selected_assertions",
        "artifact_result_receipt_semantic_digests",
    }
)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and _HEX_RE.fullmatch(value) is not None


def dimension_from_name(
    value: str | EquivalenceDimensionV1,
) -> EquivalenceDimensionV1 | None:
    if isinstance(value, EquivalenceDimensionV1):
        return value
    if not isinstance(value, str) or value.lower() in _REJECTED_DIMENSIONS:
        return None
    try:
        return EquivalenceDimensionV1(value.lower())
    except ValueError:
        return None


@dataclass(frozen=True, init=False)
class ConcreteEquivalenceTableV1:
    """Verified table handle; direct construction is deliberately unavailable."""

    table_ref: str
    table_digest: str
    canonicalizer_set_digest: str
    canonicalizer_ids: tuple[str, ...]

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ConcreteEquivalenceTableV1 must be created by the verified loader")

    @classmethod
    def _verified(
        cls,
        table_ref: str,
        canonicalizer_ids: tuple[str, ...],
    ) -> ConcreteEquivalenceTableV1:
        instance = object.__new__(cls)
        object.__setattr__(instance, "table_ref", table_ref)
        object.__setattr__(instance, "table_digest", APPROVED_TABLE_DIGEST)
        object.__setattr__(
            instance,
            "canonicalizer_set_digest",
            APPROVED_CANONICALIZER_SET_DIGEST,
        )
        object.__setattr__(instance, "canonicalizer_ids", canonicalizer_ids)
        return instance

    def is_approved(self) -> bool:
        return (
            bool(self.table_ref)
            and self.table_digest == APPROVED_TABLE_DIGEST
            and self.canonicalizer_set_digest == APPROVED_CANONICALIZER_SET_DIGEST
            and self.canonicalizer_ids
            == tuple(f"{dimension}_v1" for dimension in APPROVED_DIMENSIONS)
        )


@dataclass(frozen=True)
class CanonicalDimensionV1:
    dimension: EquivalenceDimensionV1
    value: Mapping[str, object] | None
    digest: str | None
    classification: DimensionClassificationV1
    reason: IdentityReasonV1


@dataclass(frozen=True)
class SemanticIdentityV1:
    table_ref: str
    table_digest: str
    canonicalizer_set_digest: str
    dimensions: tuple[CanonicalDimensionV1, ...]
    receipt_evidence_digest: str | None
    decision_graph_digest: str | None
    oid: str | None = None

    @property
    def complete(self) -> bool:
        return (
            len(self.dimensions) == 7
            and tuple(item.dimension.value for item in self.dimensions)
            == APPROVED_DIMENSIONS
            and all(
                item.digest
                and item.classification is DimensionClassificationV1.EQUIVALENT
                for item in self.dimensions
            )
            and is_sha256(self.receipt_evidence_digest)
            and is_sha256(self.decision_graph_digest)
        )


def approved_table_bytes() -> bytes:
    """Return the reviewed literal bytes, excluding the resource's terminal LF."""

    data = files(__package__).joinpath(_TABLE_RESOURCE).read_bytes()
    if not data.endswith(b"\n") or data.endswith(b"\n\n"):
        raise RuntimeError("approved equivalence table resource framing is invalid")
    return data[:-1]


def load_concrete_equivalence_table(
    *,
    table_ref: str,
    table_bytes: bytes,
    canonicalizer_set_digest: str,
) -> ConcreteEquivalenceTableV1 | None:
    """Load only the exact approved literal and exact canonicalizer registry."""

    if (
        not isinstance(table_ref, str)
        or not table_ref
        or table_ref.startswith("/")
        or "\\" in table_ref
        or canonicalizer_set_digest != APPROVED_CANONICALIZER_SET_DIGEST
        or not isinstance(table_bytes, bytes)
    ):
        return None
    literal = table_bytes[:-1] if table_bytes.endswith(b"\n") else table_bytes
    if hashlib.sha256(literal).hexdigest() != APPROVED_TABLE_DIGEST:
        return None
    try:
        parsed = json.loads(literal.decode("utf-8"))
        if canonical_json(parsed) != literal:
            return None
        if set(parsed) != {
            "schema_version",
            "table_id",
            "rows",
            "reason_code_schema_version",
            "canonicalizer_set_schema_version",
        }:
            return None
        if (
            parsed["schema_version"] != "1"
            or parsed["table_id"] != "ConcreteEquivalenceTableV1"
            or parsed["reason_code_schema_version"] != "1"
            or parsed["canonicalizer_set_schema_version"] != "1"
        ):
            return None
        rows = parsed["rows"]
        if not isinstance(rows, list) or any(set(row) != _ROW_KEYS for row in rows):
            return None
        dimensions = tuple(str(row["dimension"]).lower() for row in rows)
        canonicalizer_ids = tuple(str(row["canonicalizer_id"]) for row in rows)
        manifest = {
            "schema_version": "1",
            "canonicalizers": [
                {
                    "dimension": row["dimension"],
                    "canonicalizer_id": row["canonicalizer_id"],
                    "canonical_input_fields": row["canonical_input_fields"],
                }
                for row in rows
            ],
        }
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        dimensions != APPROVED_DIMENSIONS
        or canonicalizer_ids
        != tuple(f"{dimension}_v1" for dimension in APPROVED_DIMENSIONS)
        or hashlib.sha256(canonical_json(manifest)).hexdigest()
        != APPROVED_CANONICALIZER_SET_DIGEST
    ):
        return None
    return ConcreteEquivalenceTableV1._verified(table_ref, canonicalizer_ids)


def load_embedded_concrete_equivalence_table(
    *, table_ref: str = "bundle-c/ConcreteEquivalenceTableV1"
) -> ConcreteEquivalenceTableV1:
    table = load_concrete_equivalence_table(
        table_ref=table_ref,
        table_bytes=approved_table_bytes(),
        canonicalizer_set_digest=APPROVED_CANONICALIZER_SET_DIGEST,
    )
    if table is None:  # a package/resource integrity failure is not a semantic deny
        raise RuntimeError("embedded approved equivalence table failed verification")
    return table


def _has_valid_digest_fields(value: Mapping[str, Any]) -> bool:
    for field, candidate in value.items():
        if "digest" not in field:
            continue
        candidates: Sequence[object]
        if isinstance(candidate, Sequence) and not isinstance(candidate, str):
            candidates = candidate
        else:
            candidates = (candidate,)
        if not all(is_sha256(item) for item in candidates):
            return False
    return True


def canonicalize_dimension(
    dimension: str | EquivalenceDimensionV1,
    value: Mapping[str, Any] | None,
) -> CanonicalDimensionV1:
    parsed = dimension_from_name(dimension)
    if parsed is None:
        return CanonicalDimensionV1(
            EquivalenceDimensionV1.SOURCE,
            None,
            None,
            DimensionClassificationV1.UNKNOWN,
            IdentityReasonV1.UNKNOWN_DIMENSION,
        )
    if (
        not isinstance(value, Mapping)
        or value.get("unsupported")
        or value.get("ambiguous")
        or value.get("timeout")
        or value.get("plugin_unknown")
    ):
        return CanonicalDimensionV1(
            parsed,
            None,
            None,
            DimensionClassificationV1.UNKNOWN,
            IdentityReasonV1.UNSUPPORTED_INPUT,
        )
    required = _FIELDS[parsed]
    if set(value) != set(required) or any(value[field] in (None, "") for field in required):
        return CanonicalDimensionV1(
            parsed,
            None,
            None,
            DimensionClassificationV1.UNKNOWN,
            IdentityReasonV1.MISSING_INPUT,
        )
    if not _has_valid_digest_fields(value):
        return CanonicalDimensionV1(
            parsed,
            None,
            None,
            DimensionClassificationV1.UNKNOWN,
            IdentityReasonV1.UNSUPPORTED_INPUT,
        )
    try:
        normalized: dict[str, object] = {}
        for field in required:
            candidate = value[field]
            if field in _SORTED_SEQUENCE_FIELDS:
                if isinstance(candidate, str) or not isinstance(candidate, Sequence):
                    raise TypeError(field)
                candidate = tuple(sorted(candidate))
            normalized[field] = candidate
        return CanonicalDimensionV1(
            parsed,
            normalized,
            sha256(normalized),
            DimensionClassificationV1.EQUIVALENT,
            IdentityReasonV1.EQUIVALENT,
        )
    except (TypeError, ValueError):
        return CanonicalDimensionV1(
            parsed,
            None,
            None,
            DimensionClassificationV1.UNKNOWN,
            IdentityReasonV1.CANONICALIZER_ERROR,
        )


def build_semantic_identity(
    *,
    table: ConcreteEquivalenceTableV1 | None,
    values: Mapping[str, Mapping[str, Any]],
    receipt_evidence_digest: str | None,
    decision_graph_digest: str | None,
    oid: str | None = None,
) -> SemanticIdentityV1:
    dimensions = tuple(
        canonicalize_dimension(dimension, values.get(dimension))
        for dimension in APPROVED_DIMENSIONS
    )
    table_valid = table is not None and table.is_approved()
    binding_valid = is_sha256(receipt_evidence_digest) and is_sha256(decision_graph_digest)
    if not table_valid or not binding_valid:
        dimensions = tuple(
            CanonicalDimensionV1(
                item.dimension,
                item.value,
                item.digest,
                DimensionClassificationV1.UNKNOWN,
                IdentityReasonV1.STALE_TABLE,
            )
            for item in dimensions
        )
    return SemanticIdentityV1(
        table.table_ref if table_valid else "",
        table.table_digest if table_valid else "",
        table.canonicalizer_set_digest if table_valid else "",
        dimensions,
        receipt_evidence_digest,
        decision_graph_digest,
        oid,
    )
