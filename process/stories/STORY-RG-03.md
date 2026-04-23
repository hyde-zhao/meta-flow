---
story_id: "RG-03"
title: "review mode 第一组扩展"
status: "verified"
priority: "P1"
wave: "W4"
depends_on: ["RG-01", "RG-02"]
task_count: 3
created_at: "2026-04-23T11:37:06+08:00"
updated_at: "2026-04-23T13:30:00+08:00"
---

## 目标
为 `meta-pm`、`meta-se`、`meta-qa` 增加 `review_mode=true`，形成第一组评审执行体。

## 开发上下文（dev_context）
- **输入文件**：`process/HLD-review-gate.md`、`delivery/agents/meta-po.md`、review 模板
- **输出文件**：`delivery/agents/meta-pm.md`、`delivery/agents/meta-se.md`、`delivery/agents/meta-qa.md`
- **设计约束**：review mode 与生产态提示词分离；不得自评；必须输出结构化 findings
- **平台目标**：全平台一致

### AI 可执行任务清单
| TASK-ID | 动作 | 目标文件 | 描述 |
|---|---|---|---|
| T1 | 修改 | `delivery/agents/meta-pm.md` | 增加 Lane1 review mode |
| T2 | 修改 | `delivery/agents/meta-se.md` | 增加 Lane2 review mode |
| T3 | 修改 | `delivery/agents/meta-qa.md` | 增加 Lane3 review mode |

## 验证上下文（validation_context）
- **验证入口**：3 个 Agent 的 review mode 小节
- **验证方式**：人工检查
- **依赖环境**：无
- **关键验证场景**：HLD、STORY-BACKLOG、LLD 评审

## 量化验收标准（acceptance_criteria）
- [x] 3 个 Agent 都有 `review_mode=true` 入口
- [x] 输出格式均引用统一 findings 协议
- [x] review mode 与生产态职责边界清晰

## 阻塞说明（如有）
（无）
