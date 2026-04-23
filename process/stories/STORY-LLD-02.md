---
story_id: "LLD-02"
title: "STORY-LLD 模板增强（14 章节固定）"
status: "verified"
priority: "P0"
wave: "W2"
depends_on: ["LLD-01"]
task_count: 4
created_at: "2026-04-23T11:37:06+08:00"
updated_at: "2026-04-23T12:09:47+08:00"
---

## 目标
将 `STORY-LLD-TEMPLATE.md` 固化为 **始终 14 个可见章节** 的统一模板，并承载图示规则、OPEN/Spike、共享片段引用与 Tier 语义。

## 开发上下文（dev_context）
- **输入文件**：`process/HLD-lld-writing-method.md`、`delivery/skills/lld-designer/SKILL.md`
- **输出文件**：`delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md`
- **设计约束**：方案 A 生效；Tier-S 仅允许内容极简，不允许压缩章节数；必须支持共享片段引用
- **平台目标**：全平台一致

### AI 可执行任务清单
| TASK-ID | 动作 | 目标文件 | 描述 |
|---|---|---|---|
| T1 | 修改 | `delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` | 固定 14 章节结构 |
| T2 | 修改 | `delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` | 加入 tier、OPEN/Spike、确认区 |
| T3 | 修改 | `delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` | 补图示触发与共享片段引用占位 |
| T4 | 修改 | `delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` | 补接口↔测试、异常↔测试、TASK↔文件配对提示 |

## 验证上下文（validation_context）
- **验证入口**：模板正文与 frontmatter
- **验证方式**：人工检查
- **依赖环境**：无
- **关键验证场景**：Tier-S、Tier-L、共享片段、OPEN 问题

## 量化验收标准（acceptance_criteria）
- [x] 模板保留 14 个可见章节
- [x] frontmatter 含 `tier`
- [x] 模板有 OPEN/Spike 与确认区
- [x] 模板中存在图示与共享片段占位

## 阻塞说明（如有）
（无）
