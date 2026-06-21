# Context-Budgeted Meta Flow Fixture

This fixture is a minimal end-to-end sample for the context-budgeted governance chain:

`STATE.current.json -> CR summary -> context pack -> Story packet -> Story return -> evidence index -> CP result -> checkpoint ledger`.

It intentionally includes deny-default candidates such as `process/STATE.md`, `process/DEVELOPMENT-PLAN.yaml`, and the full CR document at `process/changes/CR-001.md`. Tests must prove that generated context packs and Story packets do not put those files in `allowed_reads`.
