---
project_id: "meta-flow"
release_scope: "workflow-eval-governance"
release_decision: "READY_WITH_RISK"
created_at: "2026-06-11T19:50:20+08:00"
---

# Release Notes

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-11 | host-orchestrator | 新增 workflow eval governance 发布说明 |

## 用户可见变化

- 新增 `meta-flow eval validate/run/suite-health` 本地评估命令。
- 新增 `evals/contracts/*` schema 和 generated workflow fixture。
- 新增 workflow eval / prompt bundle / case registry / suite health 治理文档。
- CP7 / meta-qa 规则现在显式区分纯代码、generated workflow、prompt-skill、meta-flow-core-code、agentic-code 和 mixed 对象。

## 兼容性

- 安装器 CLI 未破坏。
- 纯代码项目不强制 workflow eval。
- 外部 adapters 默认 disabled。

## 已知风险

- 本地 runner 使用保守 YAML-like parser，仅覆盖当前契约需要的结构。
- 外部 adapters 只定义 policy，真实运行需未来授权。
