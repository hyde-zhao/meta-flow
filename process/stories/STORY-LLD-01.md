---
story_id: "LLD-01"
title: "lld-designer 六阶段管道与输入输出契约"
status: "verified"
priority: "P0"
wave: "W1"
depends_on: []
task_count: 4
created_at: "2026-04-23T11:37:06+08:00"
updated_at: "2026-04-23T11:47:36+08:00"
---

## 目标
把 Story LLD 写作方法固化为 `lld-designer` 的正式入口契约，覆盖 6 阶段管道、输入检查、章节级输入输出契约与失败路径。

## 开发上下文（dev_context）
- **输入文件**：`process/HLD-lld-writing-method.md`、`process/ANALYSIS-meta-flow-lld-writing.md`
- **输出文件**：`delivery/skills/lld-designer/SKILL.md`
- **设计约束**：不得改变 14 章节外形；必须显式处理 OPEN/Spike；Ready Check 不得脑补缺失输入
- **平台目标**：全平台一致

### AI 可执行任务清单
| TASK-ID | 动作 | 目标文件 | 描述 |
|---|---|---|---|
| T1 | 修改 | `delivery/skills/lld-designer/SKILL.md` | 加入 6 阶段主流程 |
| T2 | 修改 | `delivery/skills/lld-designer/SKILL.md` | 固化输入/输出契约与章节映射 |
| T3 | 修改 | `delivery/skills/lld-designer/SKILL.md` | 增加失败路径与回退决策 |
| T4 | 修改 | `delivery/skills/lld-designer/SKILL.md` | 增加 Gotchas、Tier 语义与图示规则引用 |

## 验证上下文（validation_context）
- **验证入口**：`lld-designer/SKILL.md`
- **验证方式**：人工检查
- **依赖环境**：无
- **关键验证场景**：缺输入 blocked、OPEN 升级、6 阶段存在

## 量化验收标准（acceptance_criteria）
- [x] `SKILL.md` 包含 6 个阶段
- [x] 输入契约覆盖 Story/HLD/ADR/依赖/平台/CR
- [x] 输出契约覆盖 meta-dev/meta-qa/meta-po/review gate
- [x] 失败路径至少覆盖 blocked / 回退 / Spike / 人工确认

## 阻塞说明（如有）
（无）
