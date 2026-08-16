# CR-071 Release Notes (CP8 candidate snapshot)

`release_decision=READY_WITH_RISK`; aggregate CP7 is `PASS_WITH_RISK` with zero open HIGH/BLOCKER findings. This document preserves the pre-authorization CP8 snapshot. The user subsequently authorized publication as `0.5.3`; final public guidance is in `RELEASE-NOTES.md` and the versioned `*-0.5.3.md` documents. Publication still does not authorize installation, correction append, authority cutover, or production runtime.

## User-visible capability

- Typed, fail-closed work preflight and append-only scope amendments.
- Observable compatibility migration with stabilization epochs and retirement assessment.
- Semantic receipt equivalence and missing-evidence-only projection recovery.
- Atomic correction transaction contracts with preserved raw history.

## Validation

Targeted 370 passed plus 116 subtests; compatibility is effectively 829 passed plus 363 subtests after one exact stale-count repair; full is 2,558 passed plus 716 subtests with three remaining pre-batch failures, one pre-batch detector failure resolved, no new failure IDs, and no waiver. Independent aggregate CP7 reran a repaired high-risk subset with 377 passed plus 108 subtests and closed F001–F005.

The CP8 snapshot qualified create-only receipt v7 for package 0.5.2. Publication rotates the fixed locator to create-only v8 for 0.5.3 while preserving v1–v7 as immutable history.

See [MIGRATION-CR071.md](MIGRATION-CR071.md) and [ROLLBACK-CR071.md](ROLLBACK-CR071.md).
