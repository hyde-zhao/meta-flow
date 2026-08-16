"""Public capability-only migration contracts."""

from .compatibility_observation import (
    CompatibilityObservationV1,
    InputClassV1,
    ObservationError,
    observe_compatibility_decision,
    observe_compatibility_failure,
)
from .observation_storage import (
    ArchiveManifestV1,
    AtomicFileObservationPersistence,
    ObservationStore,
    PersistedObservationReceiptV1,
    RawObservationSegmentV1,
    rebuild_rollup,
    seal_and_archive_segment,
    verify_archived_segment,
)
from .retirement_admission import (
    ComparisonBasisV1,
    FullValidationObservationSnapshotV1,
    RetirementAdmissionV1,
    SnapshotComparisonV1,
    StabilizationEpochV1,
    activate_comparison_basis,
    assess_retirement,
    build_full_snapshot,
    compare_snapshots,
    record_validation_scan,
    start_stabilization_epoch,
)

__all__ = [
    "ArchiveManifestV1",
    "AtomicFileObservationPersistence",
    "CompatibilityObservationV1",
    "ComparisonBasisV1",
    "FullValidationObservationSnapshotV1",
    "InputClassV1",
    "ObservationError",
    "ObservationStore",
    "PersistedObservationReceiptV1",
    "RawObservationSegmentV1",
    "RetirementAdmissionV1",
    "SnapshotComparisonV1",
    "StabilizationEpochV1",
    "activate_comparison_basis",
    "assess_retirement",
    "build_full_snapshot",
    "compare_snapshots",
    "observe_compatibility_decision",
    "observe_compatibility_failure",
    "rebuild_rollup",
    "record_validation_scan",
    "seal_and_archive_segment",
    "start_stabilization_epoch",
    "verify_archived_segment",
]
