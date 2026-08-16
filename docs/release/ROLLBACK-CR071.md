# CR-071 Rollback Plan (CP8 candidate snapshot)

The final publication rollback contract is `ROLLBACK-0.5.3.md`; this file preserves the earlier CP8 input.

No release or migration has been executed; the protected baseline remains 0.5.2, so there is no active deployment to roll back.

For a future separately authorized rollout: stop rollout; preserve receipts and failure IDs; run a zero-write preflight against the rollback target; restore only authorized artifacts/projections without rewriting raw history; rerun targeted and compatibility validation; record a new receipt. Correction append and authority cutover require a fresh typed authorization. Production writes, credentials, and external project mutation are out of scope.
