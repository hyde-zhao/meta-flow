# Changelog

## 0.1.1 — 2026-11-23

### Added

- Claude Code `PreToolUse` hook (`mf hook pretool`) with role-aware Read/Write/Edit path guards.
- Hook installation in project `.claude/settings.json`, removed on uninstall.
- Hot/cold context tiers in `CONTEXT-POLICY.yaml`.
- Hot context size reporting and manager read budget enforcement.
- Requirement list/trace defaults scoped to the current roadmap, with `--all` and `--limit`.
- Bug/verification list defaults scoped to the current roadmap, with `--all`.
- Knowledge hot summary (`KNOWLEDGE.md`) and cold lessons (`LESSONS.md`); task packets only inject hot knowledge.
- Tail-based `mf log` and `mf context log` reads.
- `state.truncate` audit events and truncation metadata.
- Archived requirement snapshots on roadmap close.

### Fixed

- Phase exit/enter and P5 user-gate enforcement.
- Release freeze and roadmap close require the P5 exit gate.
- CLI role guard for manager/worker/maintainer commands.
- `allowed_paths`/`forbidden` enforcement using git diff and worktree snapshots.
- Dependency, wave-conflict, and lease checks on task start.
- Review verdict integrity and critical-task user acceptance.
- State rebuild from ROADMAP/tasks/handoff when `current.json` is missing.
- Version close now moves verification, bugs, and release manifests into archive.
- Requirement tracing includes archived tasks, verification, and bugs.
- `verify record --result PASS` moves bugs to `verifying` instead of closing them.
- Aligned `CONTEXT-POLICY.yaml` with the `<project>-contract/` layout.
