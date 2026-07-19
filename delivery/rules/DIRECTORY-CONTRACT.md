# Meta Flow Directory Contract

This contract defines the file-system layout used by Meta Flow agents and skills. It is a logical grouping contract, not a required physical migration of existing production `process/` directories.

## vNext Independent Project Roots

New projects use two sibling Git roots and one local relative link:

```text
<project>/                 # release repository
├── .meta-flow/workspace.yaml
└── process -> ../<project>-process

<project>-process/         # independent process repository, normally main-only
├── .meta-flow-process.yaml
├── PROJECT.yaml
├── ROADMAP.yaml           # optional
├── phases/                # optional
├── works/
├── retrospectives/
└── evolution/
```

Roadmap and Phase are optional. The minimum valid governance chain is `Project -> Work`; long projects may use `Project -> Phase -> Work` or `Project -> Roadmap -> Phase -> Work`. Different projects must never resolve to the same writable process repository or Git common dir.

The directory groups below describe legacy/G2 extended evidence locations and remain valid when selected by risk. They are not mandatory empty scaffolds for a G0/G1 Work.

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

For this repository, `process/docs/**` is the only writable canonical location for internal product, design, feature, quality, and internal release evidence. The tracked root `docs/` tree is limited to public entry points and public release documents. Do not create ignored copies or compatibility symlinks for `docs/product`, `docs/design`, `docs/features`, or `docs/quality`; the expected internal canonical copy count is exactly one.

Production projects continue to follow their own documented delivery layout. This repository-specific rule must not be projected onto a production repository without an explicit routing decision.

## Current Discovery

`process/current/` is the file-system discovery layer. It does not replace `process/state/STATE.current.json`; it points agents to the current entry files without requiring them to infer paths from conversation history.

Generated outputs:

- `process/current/CURRENT.json`
- `process/current/state.ref`
- `process/current/cr-index.ref`
- `process/current/context.ref`
- `process/current/checkpoint.ref`
- `process/current/story.ref`
- `process/current/release.ref`
- `process/current/handoff.ref`
- Best-effort symlinks with the same stem when the filesystem supports symlinks.

`CURRENT.json` must include:

- `status`: `idle`, `active`, `awaiting_gate`, or `blocked`
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

Idle state is explicit. When `active_change`, `active_story`, and `pending_gate` are empty, `CURRENT.json.status` is `idle`; `context_ref`, `checkpoint_ref`, and `story_packet_ref` are normally `null`, while `release_context_ref` and `handoff_ref` point to the latest closed-CR release and next-session handoff when available.

CR index canonical source is:

1. `process/changes/CR-INDEX.json`

`process/changes/CR-INDEX.yaml` is legacy read-only fallback for migration only and must not be created by new flows.

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

`meta-flow state current-refresh` updates `process/current/`. `meta-flow state render` also refreshes it after rendering the human summary. Producers must not hand-edit `CURRENT.json`; stale refs should be fixed by updating `STATE.current.json`, CR indexes, context capsules, or handoff/release artifacts and then rerunning `current-refresh`.
