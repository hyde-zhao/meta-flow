---
story_id: "UCD-01"
title: "use-case-discovery 核心增强"
status: "verified"
priority: "P0"
wave: "W1"
depends_on: []
task_count: 4
created_at: "2026-04-23T11:37:06+08:00"
updated_at: "2026-04-23T11:47:36+08:00"
---

## 目标
让 `use-case-discovery` 在正式输出前具备 Phase 0/1A/1B/2/3 的完整能力：头脑风暴、产物分类、`mixed` 判定、`draft/confirmed` 恢复与治理字段输出。

## 开发上下文（dev_context）
- **输入文件**：`process/HLD.md`、`process/STATE.md`
- **输出文件**：`delivery/skills/use-case-discovery/SKILL.md`
- **设计约束**：必须保留 `target_artifact_type` / `governance_mode` / `review_policy`；不得重新引入 review gate 逻辑；保持中文默认对话
- **平台目标**：Claude Code / Codex / Copilot / OpenClaw

### AI 可执行任务清单
| TASK-ID | 动作 | 目标文件 | 描述 |
|---|---|---|---|
| T1 | 修改 | `delivery/skills/use-case-discovery/SKILL.md` | 加入 Phase 0/1A/1B/2/3 结构 |
| T2 | 修改 | `delivery/skills/use-case-discovery/SKILL.md` | 固化产物类型矩阵与 `mixed` 三条硬规则 |
| T3 | 修改 | `delivery/skills/use-case-discovery/SKILL.md` | 增加 draft/confirmed 恢复和失败路径 |
| T4 | 修改 | `delivery/skills/use-case-discovery/SKILL.md` | 增加 Gotchas 与治理字段语义说明 |

## 验证上下文（validation_context）
- **验证入口**：检查 `SKILL.md` 是否覆盖 5 类产物类型与 5 个阶段
- **验证方式**：人工检查 + 结构比对
- **依赖环境**：无额外运行时
- **关键验证场景**：目标形态不明确、mixed 判断、draft 恢复、治理字段输出

## 量化验收标准（acceptance_criteria）
- [x] `SKILL.md` 显式包含 Phase 0/1A/1B/2/3
- [x] 5 类产物类型均有判定规则与追问重点
- [x] `mixed` 三条硬规则完整出现
- [x] 恢复/失败路径均有明确行为

## 阻塞说明（如有）
（无）
