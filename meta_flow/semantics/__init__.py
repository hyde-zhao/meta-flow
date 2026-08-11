"""Meta Flow 可执行语义的唯一 owner 集合。"""

from __future__ import annotations

SEMANTIC_KERNEL_VERSION = "1.0.0"
SEMANTIC_OWNER_MANIFEST = {
    "authority-pair-v2": "meta_flow.semantics.authority",
    "route-consumers-v1": "meta_flow.semantics.route",
    "native-cr-status-v1": "meta_flow.semantics.cr_status",
    "attempt-rework-v1": "meta_flow.semantics.attempt",
    "legacy-evidence-v1": "meta_flow.workflow.legacy_evidence_registry",
    "governance-ownership-v1": "meta_flow.semantics.ownership",
    "preregistration-semantics-v1": "meta_flow.semantics.preregistration",
    "outcome-boundary-v1": "meta_flow.semantics.outcome",
    "semantic-receipt-v1": "meta_flow.semantics.receipt",
    "lifecycle-transaction-v1": "meta_flow.work.lifecycle_transaction",
    "terminal-lineage-v1": "meta_flow.workflow.terminal_lineage",
    "usage-admission-v1": "meta_flow.work.usage_admission",
    "reference-lifecycle-v1": "meta_flow.project.reference_lifecycle",
    "detector-qualification-v1": "meta_flow.checks.detector_qualification",
}

__all__ = ["SEMANTIC_KERNEL_VERSION", "SEMANTIC_OWNER_MANIFEST"]
