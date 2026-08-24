"""Work lifecycle evidence-kind registry（MF-BUG-15 单一事实源）。

post-close / preflight / checker / doctor 四 consumer 共用同一 known-kind
集合与判定函数：known kind 给出确定性 ``PASS``/``BLOCKED``；unknown kind 输出
typed ``NEEDS_REVIEW`` finding（附 registry 版本 digest），不静默降级、不抛
traceback、mutation=0。

known-kind 集合的三个来源保持各自 owner 不变，本模块只做聚合与判定：
- ``policies.authz.REQUIRED_EVIDENCE_CAPABILITIES``（scope 授权能力映射）
- ``checks.adoption_readiness`` 的 victim acceptance kinds
- ``workflow.legacy_evidence_registry`` 的 legacy closed-CR kind
"""

from __future__ import annotations

from typing import Any, Mapping

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.policies.authz import (
    CAPABILITY_PREREQUISITES,
    REQUIRED_EVIDENCE_CAPABILITIES,
)

ACCEPTANCE_EVIDENCE_KINDS: frozenset[str] = frozenset(
    {
        "provider_fixture",
        "source_candidate_replay",
        "installed_artifact_replay",
    }
)
LEGACY_CLOSED_CR_EVIDENCE_KIND: str = "legacy_closed_cr_evidence"
REQUIRED_EVIDENCE_KINDS: frozenset[str] = frozenset(REQUIRED_EVIDENCE_CAPABILITIES)
KNOWN_EVIDENCE_KINDS: frozenset[str] = (
    REQUIRED_EVIDENCE_KINDS | ACCEPTANCE_EVIDENCE_KINDS | {LEGACY_CLOSED_CR_EVIDENCE_KIND}
)
REGISTRY_SCHEMA_VERSION = 1
REGISTRY_VERSION_DIGEST = canonical_digest(
    {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "acceptance_kinds": sorted(ACCEPTANCE_EVIDENCE_KINDS),
        "legacy_kinds": [LEGACY_CLOSED_CR_EVIDENCE_KIND],
        "required_kinds": sorted(REQUIRED_EVIDENCE_KINDS),
        "capability_prerequisites": {
            capability: sorted(CAPABILITY_PREREQUISITES.get(capability, ()))
            for capability in sorted(CAPABILITY_PREREQUISITES)
        },
    }
)


def evaluate_evidence_kind(
    kind: str,
    *,
    granted_capabilities: frozenset[str] | set[str] = frozenset(),
) -> dict[str, Any]:
    """typed 判定：known→确定性 PASS/BLOCKED；unknown→NEEDS_REVIEW finding。

    - 空/非字符串 kind：typed BLOCKED（fail closed，不是 NEEDS_REVIEW）。
    - known required-kind：能力映射全部被授予→PASS；缺任一→BLOCKED。
    - known acceptance/legacy kind：无能力映射要求→PASS。
    - unknown kind：NEEDS_REVIEW（附 registry 版本与 mutation=0），供人工归类后重跑。
    """

    normalized = str(kind or "").strip()
    if not normalized:
        return {
            "decision": "BLOCKED",
            "code": "evidence_kind_empty",
            "kind": "",
            "registry_version_digest": REGISTRY_VERSION_DIGEST,
            "mutation_count": 0,
        }
    if normalized not in KNOWN_EVIDENCE_KINDS:
        return {
            "decision": "NEEDS_REVIEW",
            "code": "unknown_evidence_kind",
            "kind": normalized,
            "registry_version_digest": REGISTRY_VERSION_DIGEST,
            "reason": "classify the evidence kind into the registry before retry",
            "mutation_count": 0,
        }
    required = REQUIRED_EVIDENCE_CAPABILITIES.get(normalized)
    if required is None:
        return {
            "decision": "PASS",
            "code": "known_evidence_kind",
            "kind": normalized,
            "registry_version_digest": REGISTRY_VERSION_DIGEST,
            "mutation_count": 0,
        }
    granted = set(granted_capabilities)
    missing = sorted(set(required) - granted)
    if missing:
        return {
            "decision": "BLOCKED",
            "code": "evidence_kind_capability_missing",
            "kind": normalized,
            "missing_capabilities": missing,
            "registry_version_digest": REGISTRY_VERSION_DIGEST,
            "mutation_count": 0,
        }
    return {
        "decision": "PASS",
        "code": "known_evidence_kind",
        "kind": normalized,
        "granted_capabilities": sorted(granted & set(required)),
        "registry_version_digest": REGISTRY_VERSION_DIGEST,
        "mutation_count": 0,
    }


def evaluate_required_evidence(
    required_evidence: Mapping[str, Any] | list[str] | tuple[str, ...],
    *,
    granted_capabilities: frozenset[str] | set[str] = frozenset(),
) -> list[dict[str, Any]]:
    """对一组 required evidence kind 逐个 typed 判定（保持输入顺序）。"""

    if isinstance(required_evidence, Mapping):
        values = list(required_evidence.values())
        flattened: list[str] = []
        for value in values:
            flattened.extend(str(item) for item in (value if isinstance(value, (list, tuple)) else [value]))
        kinds = flattened
    else:
        kinds = [str(item) for item in required_evidence]
    return [evaluate_evidence_kind(kind, granted_capabilities=granted_capabilities) for kind in kinds]
