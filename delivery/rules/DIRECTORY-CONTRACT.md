# Meta Flow Directory Contract

This contract defines the file-system layout used by Meta Flow agents and skills. It is a logical grouping contract, not a required physical migration of existing production `process/` directories.

Runtime delivery semantics are machine-owned by `delivery/rules/DELIVERY-RUNTIME-CONTRACT.json`; this document is its human-readable directory facade. Platform target paths remain owned by `delivery/doc/PLATFORM-CONTRACTS.yaml`.

## vNext Independent Project Roots

New projects use two sibling Git roots and reciprocal portable bindings. The default route has no local process link:

```text
<project>/                 # release repository
└── .meta-flow/workspace.yaml  # tracked release-side binding

<project>-process/         # independent process repository, normally main-only
├── .meta-flow-process.yaml
├── PROJECT.yaml
├── ROADMAP.yaml           # optional
├── phases/                # optional
├── works/
├── retrospectives/
└── evolution/
```

The default is `route_mode=sibling-binding` with `--process-link-mode none`. `relative-symlink` is an explicit compatibility mode for legacy Agent/Skill assets that still access literal `process/...` paths. Binding-only mode requires the release `process` entry to be absent; compatibility mode requires `process -> ../<project>-process` and rejects absolute links.

Every `process/...` string consumed by an Agent or Skill is a logical ref. Before file-system I/O it must be resolved only through `meta-flow project resolve-ref --project-root <release-root> --logical-ref <process/...> --format json`. The returned absolute `resolved_path` is transient and must not be persisted. Exit code 2 is fail-closed; callers must not strip the prefix, discover siblings, recreate a link, or silently select a legacy route.

Both binding files must agree on schema, layout, project identity, route mode, and reciprocal sibling routes. The current `workspace_parent` anchor accepts exactly one safe sibling name and rejects absolute paths, `..`, sibling discovery, and non-sibling layouts. Roadmap and Phase are optional. The minimum valid governance chain is `Project -> Work`; long projects may use `Project -> Phase -> Work` or `Project -> Roadmap -> Phase -> Work`. Different projects must never resolve to the same writable process repository or Git common dir.

`.meta-flow/workspace.yaml` is tracked machine truth. `.meta-flow/INSTALL-MANIFEST.yaml` is device-local installer state and must remain gitignored. A workspace-root README is human navigation only and must never be used for route resolution.

For `fresh-vnext-bootstrap` from a legacy shared-artifact subdirectory, create `legacy/LEGACY-SOURCE.yaml` only after successful local init apply and before the first process-repository commit. Schema version 1 records `project_id`, `migration_mode`, `source_repo_url`, `source_ref`, the exact `source_oid` frozen by `git ls-remote`, `source_subpath`, `source_mode=read-only`, `copied_history=false`, `deletion_authorized=false`, `history_rewrite_authorized=false`, `snapshot_date`, and a short note. It must not contain a device-local absolute path or credentials. This source shape is not eligible for the current `project adopt`; no bulk legacy copy or history rewrite is allowed.

The directory groups below describe legacy/G2/G3 extended evidence locations and remain valid when selected by risk. They are not mandatory empty scaffolds for a G0/G1 Work. GovernanceRiskProfile V2：G2=scope-goal-note；G3=原 G2 完整流程（等价 V1 G2）；只有用户显式选择 G3。

## Roots

| Root | Zone | Purpose |
|---|---|---|
| `docs/` | warm | Public tracked documentation. For meta-flow self-development, internal product/design/quality documents are canonical only under `process/docs/`. |
| `process/` | hot / warm / cold | Runtime state, context, checks, checkpoints, ledgers, CRs, Story work, evidence, handoffs, and archives. |
| `delivery/` | warm | Installable Meta Flow agents, skills, rules, docs, and scripts. |
| `.agents/` | warm | Meta Flow self-development source agents and skills. |

## Process Groups

| Group | Directories | Default Zone |
|---|---|---|
| State and routing | `process/state/`, `process/current/`, `process/context/`, `process/handoffs/` | hot |
| Checks and gates | `process/checks/`, `process/checkpoints/`, `process/discussions/` | warm, with discussions deny-default |
| Changes and stories | `process/changes/`, `process/stories/`, `process/returns/`, `process/evidence/`, `process/design-deltas/` | warm |
| Release and archive | `process/release/`, `process/archive/` | release warm, archive cold |
| Policy and config | `process/policies/`, `process/constraints/`, `process/registers/` | warm |
| Support | `process/backups/`, `process/baseline/`, `process/plans/`, `process/reviews/`, `process/runbooks/`, `process/docs/` | warm |

## Meta-flow Self-development Canonical Docs

For this repository, `process/docs/**` is the only writable canonical location for internal product, design, feature, quality, and internal release evidence. The tracked root `docs/` tree is limited to public entry points and public release documents. Do not create ignored copies or compatibility symlinks for `docs/product`, internal design evidence under `docs/design`, `docs/features`, or `docs/quality`; the expected internal canonical copy count is exactly one.

Two release-root machine contracts are explicit exceptions to the internal-document rule: `docs/design/PACKAGE-IDENTITY.yaml` and `docs/design/MODULE-BOUNDARIES.yaml`. They are not HLD or design evidence; the production checkers consume them relative to the release root, so they must be tracked, writable machine truth and must not be ignored. `process/policies/SOURCE-OF-TRUTH-MAP.yaml` owns these exact paths. Every other Meta Flow self-development design document, including the human Source-of-Truth summary, remains canonical only under `process/docs/design/**`; no other release-root `docs/design/**` exception is permitted.

Production projects continue to follow their own documented delivery layout. This repository-specific rule must not be projected onto a production repository without an explicit routing decision.

## Current Discovery

`process/current/` is the file-system discovery layer. It does not replace `process/state/STATE.current.json`; it points agents to the current entry files without requiring them to infer paths from conversation history.

Generated outputs:

- Canonical, trackable discovery truth: `process/current/CURRENT.json` and each present same-stem `*.ref` file (`state.ref`, `cr-index.ref`, `change.ref`, `context.ref`, `checkpoint.ref`, `story.ref`, `release.ref`, and `handoff.ref`).
- Local, regenerable discovery aliases: same-stem symlinks (`state`, `cr-index`, `change`, `context`, `checkpoint`, `story`, `release`, and `handoff`) when the filesystem supports symlinks.

The symlink aliases are never formal truth and must not be staged. `current-refresh` maintains an exact managed block in the process-root `.gitignore` so the aliases remain `ignored_generated`; it preserves unrelated ignore rules and fails before rewriting an unsafe or malformed `.gitignore`. A fresh clone may reconstruct the aliases from tracked state and discovery inputs without making the worktree dirty.

`CURRENT.json` must include:

- `status`: `idle`, `active`, `awaiting_gate`, `awaiting_authorization`, or `blocked`
- `health`: `ok`, `stale_refs`, or `incomplete`
- `state_ref`
- `cr_index_ref`
- `available_index_refs`
- `change_ref`
- `context_ref`
- `checkpoint_ref`
- `story_packet_ref`
- `release_context_ref`
- `handoff_ref`
- `stale_refs`

Idle state is explicit. When `active_change`, `active_story`, and `pending_gate` are empty and no typed authorization is pending, `CURRENT.json.status` is `idle`; `context_ref`, `checkpoint_ref`, and `story_packet_ref` are normally `null`. `next_session_handoff_ref` 字段存在且为显式 `null` 时，`handoff_ref` 必须保持 `null`；只有 legacy payload 缺少该字段时才允许发现最新历史 handoff。

CR index canonical source is:

1. `process/changes/CR-INDEX.json`

The authoritative inputs are native `process/changes/CR-*.md` formal objects plus their PROJECT/WORK scope. `CR-INDEX.json` is a disposable projection: its items are numeric-CR ordered, carry a semantic digest, and are rebuilt without reading the previous index, summary bodies, ledgers, or any legacy repository. `process/changes/CR-INDEX.yaml` and legacy repository indexes are read-only migration inputs only; new flows must not copy or regenerate them.

Status changes use `meta-flow cr status-sync` plan/apply/recovery. Transaction manifests and immutable before/after recovery payloads live only under the process repository Git common dir private Meta Flow area; they are not process artifacts and must not be committed. `process/changes/CR-INDEX.json` is the last worktree target written by a successful transaction.

Decision Bundle evidence is append-only in `process/state/GATE-LEDGER.ndjson`: one bundle revision may have one user confirmation, while every subgate keeps independent precondition/result/evidence and stop events. Git scope inventories classify candidate paths into eight classes before freeze; tracked symlink, missing and ignored generated outputs remain validation-only and never enter a staged mutation set.

## Zone Read Rules

Hot files are default-readable when listed by a context pack:

- `process/state/STATE.current.json`
- `process/current/CURRENT.json`
- Current context capsule or Story packet

Warm files are read only when listed by `allowed_reads`, `must_read`, or `read_if_needed`:

- `process/checks/*.result.json`
- `process/checkpoints/CP*.md`
- `process/changes/summaries/*.summary.json`
- `process/evidence/*.index.json`
- Current CR / Story summaries and current release context

Cold files are deny-default:

- `process/archive/**`
- Historical discussion logs
- Legacy full state or planning longforms such as `process/STATE.md` and `process/DEVELOPMENT-PLAN.yaml`

Reading deny-default files requires a valid `full_doc_read_reason` and a read expansion event in `process/state/READ-EXPANSION-LEDGER.ndjson`.

## Generation Rules

`meta-flow state current-refresh` updates `process/current/` and the process-root `.gitignore` managed alias block. `meta-flow state render` also refreshes it after rendering the human summary. Producers must not hand-edit `CURRENT.json`, `*.ref`, or the generated symlink aliases; stale refs should be fixed by updating `STATE.current.json`, CR indexes, context capsules, or handoff/release artifacts and then rerunning `current-refresh`.
