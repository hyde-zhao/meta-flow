# Meta Flow Docs

This directory is the public documentation surface for the source repository.

## Public Docs

These files are tracked in the `meta-flow` source repository:

| Path | Purpose |
|---|---|
| `docs/release/RELEASE-NOTES.md` | Public release notes derived from CP8 release evidence |
| `docs/USER-MANUAL.md` | User manual entry, linked to `delivery/doc/USER-MANUAL.md` |

## vNext Internal Process Docs

新项目不再把多个项目的内部文档写入共享 artifact working tree。每个项目拥有 sibling `<project>-process` Git 仓库，发布库通过相对 `process` 软链接访问它。内部产品、设计、质量、执行、复盘和进化记录都属于该项目的独立过程库；Roadmap/Phase 按项目规模可选。

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
