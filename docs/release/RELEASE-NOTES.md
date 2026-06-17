---
project_id: "meta-flow"
release_scope: "meta-flow-artifact-routing-and-eval-governance"
release_decision: "READY_WITH_RISK"
created_at: "2026-06-17T13:49:25+08:00"
---

# Release Notes

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-11 | host-orchestrator | 新增 workflow eval governance 发布说明 |
| 1.1 | 2026-06-17 | host-orchestrator | 扩展至 process/docs artifact routing、workspace health 和 advanced eval runner |

## 发布范围

| 范围 | 内容 | 证据 |
|---|---|---|
| Workflow eval governance | `meta-flow eval validate/run/suite-health`、eval contracts、fixture、suite health、optional adapter policy | CR-018..CR-023 |
| Process artifact routing | `process/` 外置到 `/home/hyde/projects/meta-flow-artifacts/process/meta-flow`，源码仓库保留 symlink | CR-024、CR-026 |
| Docs artifact routing | `docs/` 外置到 `/home/hyde/projects/meta-flow-artifacts/docs/meta-flow`，源码仓库保留 symlink | CR-027 |
| Eval runner hardening | 新增 grader、case results 和 expected failure 语义，新增 advanced fixture | CR-028 |

## 用户可见变化

- 新增 `meta-flow workspace check/link`，用于检查或建立外置 process 工作区。
- `meta-flow status`、`meta-flow next`、`meta-flow doctor` 和 CR tracking 会先检查 process symlink health；断链或项目不匹配时阻断恢复。
- 源码仓库不再跟踪 `process/` 和 `docs/` 普通过程目录；过程文件由 `meta-flow-artifacts` 仓库跟踪。
- 新增 `meta-flow eval validate/run/suite-health` 本地评估命令和 workflow eval fixtures。
- eval runner 新增 gate、state machine、table schema、artifact trace、expected failure 等 deterministic grader。

## 兼容性

- 安装器 CLI 未破坏。
- 已 clone 的源码仓库需要同时准备 artifact repo，或由 `meta-flow workspace link` 指向正确 artifact root。
- 纯代码项目不强制 workflow eval。
- 外部 adapters 默认 disabled，真实运行需要独立 runtime authorization。

## 已知风险

| 风险 | 等级 | 处理 |
|---|---|---|
| 本地 eval runner 使用保守 YAML-like parser | LOW | 保持 eval config 简单；复杂嵌套需要后续 CR 引入正式 parser |
| 外部 adapters 只定义 policy | INFO | 真实运行前创建 runtime_authorization CR 或 Spike |
| `process/` 和 `docs/` 依赖 symlink | MEDIUM | 缺失或断链时 hard-stop，由用户提供 artifact 目录后再继续 |
