---
story_id: "RG-05"
title: "分派表与灰度落地"
status: "verified"
priority: "P1"
wave: "W5"
depends_on: ["UCD-03", "RG-03", "RG-04"]
task_count: 3
created_at: "2026-04-23T11:37:06+08:00"
updated_at: "2026-04-23T13:30:00+08:00"
---

## 目标
把 reviewer 分派表、灰度落地策略与规则同步写入正式对象，完成 HLD/LLD 先试点的 rollout 设计。

## 开发上下文（dev_context）
- **输入文件**：`process/HLD-review-gate.md`、`delivery/agents/meta-pm.md`、`delivery/agents/meta-se.md`、`delivery/agents/meta-dev.md`、`delivery/agents/meta-qa.md`、`delivery/agents/meta-doc.md`
- **输出文件**：`delivery/skills/README.md`、`delivery/rules/AGENTS.md`、`delivery/rules/CLAUDE.md`、`delivery/rules/copilot-instructions.md`
- **设计约束**：分派表必须与实际 review mode 实现一一对应；灰度顺序先 HLD/LLD，后扩其他文档
- **平台目标**：全平台一致

### AI 可执行任务清单
| TASK-ID | 动作 | 目标文件 | 描述 |
|---|---|---|---|
| T1 | 修改 | `delivery/skills/README.md` | 写入 reviewer 分派与依赖关系 |
| T2 | 修改 | `delivery/rules/AGENTS.md` | 写入 review gate rollout 规则 |
| T3 | 修改 | `delivery/rules/CLAUDE.md`,`delivery/rules/copilot-instructions.md` | 同步平台规则口径 |

## 验证上下文（validation_context）
- **验证入口**：README/rules 一致性
- **验证方式**：人工检查
- **依赖环境**：无
- **关键验证场景**：HLD、LLD 先试点；后续扩展文档

## 量化验收标准（acceptance_criteria）
- [x] README 中存在 reviewer 分派表
- [x] 3 份 rules 文档都写明灰度顺序
- [x] rollout 顺序与 HLD-review-gate 一致

## 阻塞说明（如有）
已解决：共享评审资产固定为 `delivery/skills/review-artifact-protocol/`，并由 `meta-po` 与各 reviewer lane 共同引用。
