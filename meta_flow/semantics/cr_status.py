"""native CR lifecycle/readiness/gate tuple 与 transition graph 的唯一 owner。"""

NATIVE_LIFECYCLE_STATUSES = frozenset(
    {"candidate", "active", "blocked", "closed", "cancelled", "superseded"}
)
NATIVE_READINESS_STATUSES = frozenset(
    {"ready", "ready_with_risk", "not_ready", "n/a"}
)
NATIVE_GATE_STATUSES = frozenset(
    {
        "not_started",
        "cp2_pending",
        "cp3_pending",
        "cp5_pending",
        "cp7_pending",
        "cp8_pending",
        "implementation_in_progress",
        "verification_in_progress",
        "cp8_closed",
        "cp8_recovery_closed",
        "closed",
    }
)
ACTIVE_GATES = (
    "cp2_pending",
    "cp3_pending",
    "cp5_pending",
    "implementation_in_progress",
    "verification_in_progress",
    "cp7_pending",
    "cp8_pending",
)


def _strip_scalar(value: object) -> str:
    raw = str(value or "").strip()
    if " #" in raw:
        raw = raw.split(" #", 1)[0].rstrip()
    return raw.strip().strip("`").strip().strip('"').strip("'")


def _normalize_formal_status(value: object) -> str:
    status = _strip_scalar(value).lower()
    if not status:
        return ""
    if status.startswith("closed") or status in {"implemented", "approved"}:
        return "closed"
    if status.startswith("cancelled") or status == "deleted-by-user":
        return "cancelled"
    if status.startswith("blocked"):
        return "blocked"
    if status.startswith("active"):
        return "active"
    if status in {"spike-candidate", "spike candidate"}:
        return "spike_candidate"
    return status


def normalize_lifecycle_status(value: object, *, fallback_status: str = "") -> str:
    lifecycle = _strip_scalar(value).lower().replace("-", "_")
    if lifecycle in NATIVE_LIFECYCLE_STATUSES:
        return lifecycle
    status = _normalize_formal_status(fallback_status)
    if status in {"candidate", "spike_candidate"}:
        return "candidate"
    if status in {"open", "pending"}:
        return "active"
    if status in {"active", "blocked", "closed", "cancelled", "superseded"}:
        return status
    if status in {"converted-to-spike", "converted_to_spike"}:
        return "active"
    return lifecycle


def normalize_readiness_status(value: object) -> str:
    readiness = _strip_scalar(value).lower().replace("-", "_")
    if readiness in {"na", "not_applicable", "not-applicable"}:
        return "n/a"
    return readiness


def normalize_gate_status(value: object, *, fallback_gate: str = "") -> str:
    gate = _strip_scalar(value or fallback_gate).lower().replace("-", "_")
    if gate in {"not_started", "not-started", "未启动"}:
        return "not_started"
    return gate


def validate_native_status_tuple(
    lifecycle_status: str,
    readiness_status: str,
    gate_status: str,
) -> list[str]:
    lifecycle = normalize_lifecycle_status(lifecycle_status)
    readiness = normalize_readiness_status(readiness_status)
    gate = normalize_gate_status(gate_status)
    if lifecycle == "candidate":
        legal = readiness == "not_ready" and gate == "not_started"
    elif lifecycle in {"active", "blocked"}:
        legal = readiness == "not_ready" and gate in ACTIVE_GATES
    elif lifecycle == "closed":
        legal = readiness in {"ready", "ready_with_risk"} and gate in {
            "closed",
            "cp8_closed",
            "cp8_recovery_closed",
        }
    elif lifecycle in {"cancelled", "superseded"}:
        legal = readiness == "n/a" and gate == "closed"
    else:
        legal = False
    if legal:
        return []
    return [
        "illegal native status tuple: "
        f"{lifecycle or '-'} / {readiness or '-'} / {gate or '-'}"
    ]


def native_transition_edges() -> frozenset[
    tuple[tuple[str, str, str], tuple[str, str, str]]
]:
    edges: set[tuple[tuple[str, str, str], tuple[str, str, str]]] = set()
    for left, right in zip(ACTIVE_GATES, ACTIVE_GATES[1:], strict=False):
        edges.add((("active", "not_ready", left), ("active", "not_ready", right)))
    edges.update(
        {
            (("candidate", "not_ready", "not_started"), ("active", "not_ready", "cp2_pending")),
            (("candidate", "not_ready", "not_started"), ("active", "not_ready", "cp3_pending")),
            (("active", "not_ready", "cp8_pending"), ("closed", "ready", "cp8_closed")),
            (("active", "not_ready", "cp8_pending"), ("closed", "ready_with_risk", "cp8_closed")),
            (("blocked", "not_ready", "cp8_pending"), ("closed", "ready_with_risk", "cp8_recovery_closed")),
        }
    )
    for gate in ACTIVE_GATES:
        edges.add((("active", "not_ready", gate), ("blocked", "not_ready", gate)))
        edges.add((("blocked", "not_ready", gate), ("active", "not_ready", gate)))
        for lifecycle in ("active", "blocked"):
            for readiness in ("ready", "ready_with_risk"):
                edges.add(
                    (
                        (lifecycle, "not_ready", gate),
                        ("closed", readiness, "closed"),
                    )
                )
    return frozenset(edges)


NATIVE_TRANSITION_EDGES = native_transition_edges()


def validate_native_transition(
    before: tuple[str, str, str],
    after: tuple[str, str, str],
    *,
    historical_migration: bool = False,
) -> list[str]:
    target_errors = validate_native_status_tuple(*after)
    if target_errors:
        return target_errors
    source = (
        normalize_lifecycle_status(before[0]),
        normalize_readiness_status(before[1]),
        normalize_gate_status(before[2]),
    )
    target = (
        normalize_lifecycle_status(after[0]),
        normalize_readiness_status(after[1]),
        normalize_gate_status(after[2]),
    )
    if historical_migration:
        if target[0] == "active" and source[0] in {
            "closed",
            "cancelled",
            "superseded",
        }:
            return ["historical migration must not reactivate a terminal CR"]
        return []
    if source == target or (source, target) in NATIVE_TRANSITION_EDGES:
        return []
    return [f"illegal native status transition: {'/'.join(source)} -> {'/'.join(target)}"]


__all__ = [
    "ACTIVE_GATES",
    "NATIVE_GATE_STATUSES",
    "NATIVE_LIFECYCLE_STATUSES",
    "NATIVE_READINESS_STATUSES",
    "NATIVE_TRANSITION_EDGES",
    "native_transition_edges",
    "normalize_gate_status",
    "normalize_lifecycle_status",
    "normalize_readiness_status",
    "validate_native_status_tuple",
    "validate_native_transition",
]
