"""7 个 process route 直接消费者的唯一分类表。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RouteConsumerClass(StrEnum):
    CANONICAL_BINDING_READ = "canonical-binding-read"
    LEGACY_MUTATION_POSTCONDITION = "legacy-mutation-postcondition"
    REGRESSION_ONLY = "regression-only"
    DEPRECATED = "deprecated"


@dataclass(frozen=True)
class RouteConsumerPolicy:
    consumer_id: str
    classification: RouteConsumerClass
    vnext_read: bool
    legacy_fallback: bool
    owner: str


ROUTE_CONSUMER_POLICIES = {
    policy.consumer_id: policy
    for policy in (
        RouteConsumerPolicy(
            "require-process-health",
            RouteConsumerClass.DEPRECATED,
            False,
            True,
            "meta_flow.workspace.routing",
        ),
        RouteConsumerPolicy(
            "legacy-workspace-link-postcheck",
            RouteConsumerClass.LEGACY_MUTATION_POSTCONDITION,
            False,
            True,
            "meta_flow.workspace.routing",
        ),
        RouteConsumerPolicy(
            "legacy-workspace-bootstrap-postcheck",
            RouteConsumerClass.LEGACY_MUTATION_POSTCONDITION,
            False,
            True,
            "meta_flow.workspace.routing",
        ),
        RouteConsumerPolicy(
            "workspace-git-discovery",
            RouteConsumerClass.CANONICAL_BINDING_READ,
            True,
            True,
            "meta_flow.workspace.git_sync",
        ),
        RouteConsumerPolicy(
            "adoption-readiness",
            RouteConsumerClass.CANONICAL_BINDING_READ,
            True,
            True,
            "meta_flow.checks.adoption_readiness",
        ),
        RouteConsumerPolicy(
            "workspace-doctor",
            RouteConsumerClass.REGRESSION_ONLY,
            True,
            True,
            "meta_flow.cli",
        ),
        RouteConsumerPolicy(
            "workspace-check",
            RouteConsumerClass.CANONICAL_BINDING_READ,
            True,
            True,
            "meta_flow.cli",
        ),
    )
}


def route_consumer_policy(consumer_id: str) -> RouteConsumerPolicy:
    try:
        return ROUTE_CONSUMER_POLICIES[consumer_id]
    except KeyError as exc:
        raise ValueError(f"unregistered route consumer: {consumer_id!r}") from exc


__all__ = [
    "ROUTE_CONSUMER_POLICIES",
    "RouteConsumerClass",
    "RouteConsumerPolicy",
    "route_consumer_policy",
]
