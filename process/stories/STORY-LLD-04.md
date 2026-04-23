---
story_id: "LLD-04"
title: "LLD 方法试点 Story"
status: "verified"
priority: "P1"
wave: "W6"
depends_on: ["LLD-03", "RG-05"]
task_count: 3
created_at: "2026-04-23T11:37:06+08:00"
updated_at: "2026-04-23T13:30:00+08:00"
---

## 目标
选 1 个试点 Story，验证新 LLD 写作方法、消费契约与 review gate 的组合可用。

## 开发上下文（dev_context）
- **输入文件**：`process/HLD-lld-writing-method.md`、`process/HLD-review-gate.md`、`process/DEVELOPMENT-PLAN.yaml`
- **输出文件**：`process/stories/STORY-PILOT-01.md`、`process/stories/STORY-PILOT-01-LLD.md`
- **设计约束**：试点 Story 必须命中新 LLD 方法的关键场景；不得绕开 LLD 审核门
- **平台目标**：仓库运行态试点

### AI 可执行任务清单
| TASK-ID | 动作 | 目标文件 | 描述 |
|---|---|---|---|
| T1 | 创建 | `process/stories/STORY-PILOT-01.md` | 选取试点 Story 卡片 |
| T2 | 创建 | `process/stories/STORY-PILOT-01-LLD.md` | 按新 LLD 方法起草试点 LLD |
| T3 | 记录 | `process/STATE.md` 或试点说明 | 记录试点发现与是否需回流 HLD/规则 |

## 验证上下文（validation_context）
- **验证入口**：试点 Story 卡片与试点 LLD
- **验证方式**：人工检查 + review gate 试运行
- **依赖环境**：仓库运行态
- **关键验证场景**：14 章节固定、OPEN/Spike、review gate 消费

## 量化验收标准（acceptance_criteria）
- [x] 试点 LLD 使用完整 14 章节
- [x] review gate 能读取试点 LLD 进行评审
- [x] 试点结果能反向指导后续收敛

## 阻塞说明（如有）
已满足：RG-05 已完成，试点 Story 与试点 LLD 已创建并记录到 `STATE.md`。
