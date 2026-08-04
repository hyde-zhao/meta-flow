# Meta Flow Docs

This directory is the public documentation surface for the source repository.

## Public Docs

These files are tracked in the `meta-flow` source repository:

| Path | Purpose |
|---|---|
| `docs/release/RELEASE-NOTES.md` | Public release notes derived from CP8 release evidence |
| `docs/USER-MANUAL.md` | User manual entry, linked to `delivery/doc/USER-MANUAL.md` |

## vNext Internal Process Docs

新项目不再把多个项目的内部文档写入共享 artifact working tree。每个项目拥有 sibling
`<project>-process` Git 仓库，发布库通过 tracked `.meta-flow/workspace.yaml` 的
`sibling-binding` 解析过程仓。内部产品、设计、质量、执行、复盘和进化记录都属于该项目
的独立过程库；Roadmap/Phase 按项目规模可选。默认不会创建 `process` 软链接；软链接只属于显式 legacy
`relative-symlink` 兼容模式。`process/...` 始终是逻辑引用，首次 I/O 通过
`meta-flow project resolve-ref` 解析。

## Routine Work Efficiency Contract

普通 G0/G1 Work 使用“澄清目标 → 计划切片 → 直接实施 → 分层验证”四阶段路线，默认
不运行功能 Agent 或 CP0-CP8 自治理。验证按 targeted → compatibility → full 执行，
相同 source/profile fingerprint 的 PASS receipt 才可复用；失败只回当前切片。

默认查询由单 operation 读取上下文限制在 5 个对象以内，并对 scope 外、第 6 个对象、
stale snapshot 和 plan/apply context 复用执行读取前阻断。Capsule 全文扩读只接受五个
机器可验证 reason。CURRENT、summary、evidence 和 WORKFLOW-HEALTH 在只有 volatile
时间字段或零增量变化时保持 actual mutation=0；transaction 的 OID、scope、dirty-path、
preimage、append-only ledger 与 recovery 验证不被放宽。完整操作说明见
[`delivery/doc/USER-MANUAL.md`](../delivery/doc/USER-MANUAL.md)。

当前 meta-flow 仓库尚未执行真实路由迁移，因此下方 shared artifact 路径只描述 legacy 本地兼容状态，不代表新项目默认布局。

## Legacy Internal Archived Docs

Internal design, quality, release-readiness and process notes are archived in:

```text
<artifact-root>/docs/meta-flow

`artifact-root` 必须通过项目根的相对路径记录，例如 `../meta-flow-artifacts`，不得在文档或运行态元数据中固化 `/home/...` 这类设备相关绝对路径。
```

For local continuity, these paths may exist as ignored symlinks:

```text
docs/design
docs/features
docs/quality
docs/release/DEPLOY-CHECKLIST.md
docs/release/FEEDBACK.md
docs/release/MIGRATION.md
docs/release/ROLLBACK.md
docs/MODIFICATION-LOG.md
docs/SKILL-DEVELOPMENT-STANDARD.md
```

Those symlinks keep legacy agent paths readable without publishing internal
design, quality or checkpoint evidence in the source repository.
