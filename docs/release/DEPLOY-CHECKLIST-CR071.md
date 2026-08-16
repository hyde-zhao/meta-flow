# CR-071 Deploy Checklist (CP8 candidate snapshot)

This pre-authorization snapshot is superseded for publication by `DEPLOY-CHECKLIST-0.5.3.md`.

| Check | Evidence / action | Status |
|---|---|---|
| Bind aggregate CP7 result/report/review | CP7-BATCH refs and `process/checks/CP7-STORY-CR071-BATCH.result.json` | PASS_WITH_RISK |
| Targeted and compatibility layers | 370/116 and effective 829/363 layered receipt | PASS |
| Full suite | 2,558 passed + 716 subtests; three pre-batch failures remain; one pre-batch detector failure resolved; new failures 0; no waiver | RISK ACCEPTANCE REQUIRED |
| Provider package qualification | `docs/release/PROVIDER-QUALIFICATION-0.5.2.json`; activation receipt v7 `CURRENT`; v1-v6 immutable | PASS |
| Revalidate source/process OIDs, preimages, dirty paths | At any future apply | PENDING |
| Install, upgrade, idempotence, uninstall dry-runs | N/A for this source-only candidate because installer/platform-path leaves did not change; real installation still requires separate typed authorization | N/A |
| Commit, push, tag, GitHub Release | Authorized later for exact version 0.5.3; see versioned checklist | SUPERSEDED |
| Install, correction/cutover, production runtime | Separate typed authorization still required | NOT AUTHORIZED |
