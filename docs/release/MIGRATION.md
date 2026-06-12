---
project_id: "meta-flow"
release_scope: "workflow-eval-governance"
created_at: "2026-06-11T19:50:20+08:00"
---

# Migration

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-11 | host-orchestrator | 新增 workflow eval governance 迁移说明 |

## 状态字段

| 字段 | 迁移影响 | 处理 |
|---|---|---|
| `STATE.md.target_project_profile` | 新增可选字段 | 旧 STATE 缺失时按模板补齐，默认 `project_kind=unknown` |
| Story `verification_gate.validation_target` | 新增可选字段 | 旧 Story 缺失时按 `validation_mode` 和项目类型推断或写 N/A |
| Story `verification_gate.workflow_eval` | 新增可选字段 | 纯代码项目默认 N/A，workflow / prompt / mixed 项按 CP7 要求补证据 |

## 兼容性

- 旧纯代码项目无需迁移到 workflow eval。
- 旧验证报告仍可作为 legacy evidence，但新 CP7 建议补 `validation_target`。
- 外部 adapter 不自动启用。
