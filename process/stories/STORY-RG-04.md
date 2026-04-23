---
story_id: "RG-04"
title: "review mode 第二组扩展"
status: "verified"
priority: "P1"
wave: "W4"
depends_on: ["RG-01", "RG-02"]
task_count: 2
created_at: "2026-04-23T11:37:06+08:00"
updated_at: "2026-04-23T13:30:00+08:00"
---

## 目标
为 `meta-dev`、`meta-doc` 增加 `review_mode=true`，补齐实现可行性与交付文档视角。

## 开发上下文（dev_context）
- **输入文件**：`process/HLD-review-gate.md`、review 模板
- **输出文件**：`delivery/agents/meta-dev.md`、`delivery/agents/meta-doc.md`
- **设计约束**：meta-dev 关注可实现性；meta-doc 关注交付可读性；不得和生产态混写
- **平台目标**：全平台一致

### AI 可执行任务清单
| TASK-ID | 动作 | 目标文件 | 描述 |
|---|---|---|---|
| T1 | 修改 | `delivery/agents/meta-dev.md` | 增加 Lane2 review mode（实现视角） |
| T2 | 修改 | `delivery/agents/meta-doc.md` | 增加交付文档 review mode |

## 验证上下文（validation_context）
- **验证入口**：2 个 Agent 的 review mode 小节
- **验证方式**：人工检查
- **依赖环境**：无
- **关键验证场景**：LLD、README、USER-MANUAL 评审

## 量化验收标准（acceptance_criteria）
- [x] meta-dev review mode 明确关注接口/可实现性
- [x] meta-doc review mode 明确关注交付文档可读性

## 阻塞说明（如有）
（无）
