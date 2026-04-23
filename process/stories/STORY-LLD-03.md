---
story_id: "LLD-03"
title: "LLD 生产/消费契约对齐"
status: "verified"
priority: "P0"
wave: "W3"
depends_on: ["LLD-01", "LLD-02"]
task_count: 4
created_at: "2026-04-23T11:37:06+08:00"
updated_at: "2026-04-23T13:30:00+08:00"
---

## 目标
同步 `meta-dev`、`meta-qa` 与平台规则对 LLD 的消费语义，确保 Story LLD 可直接被实现、验证与门禁消费。

## 开发上下文（dev_context）
- **输入文件**：`process/HLD-lld-writing-method.md`、`delivery/skills/lld-designer/SKILL.md`、`delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md`
- **输出文件**：`delivery/agents/meta-dev.md`、`delivery/agents/meta-qa.md`、`delivery/rules/AGENTS.md`、`delivery/rules/CLAUDE.md`、`delivery/rules/copilot-instructions.md`
- **设计约束**：meta-dev 负责生成；meta-qa 负责消费；不得把 review gate 逻辑写回 LLD 方法本体
- **平台目标**：全平台一致

### AI 可执行任务清单
| TASK-ID | 动作 | 目标文件 | 描述 |
|---|---|---|---|
| T1 | 修改 | `delivery/agents/meta-dev.md` | 写清 LLD 起草与 Ready Check 规则 |
| T2 | 修改 | `delivery/agents/meta-qa.md` | 写清 LLD 消费、测试入口和回归读取规则 |
| T3 | 修改 | `delivery/rules/AGENTS.md` | 同步 LLD 14 章节与消费契约 |
| T4 | 修改 | `delivery/rules/CLAUDE.md`,`delivery/rules/copilot-instructions.md` | 同步平台规则口径 |

## 验证上下文（validation_context）
- **验证入口**：Agent/rules 文本一致性
- **验证方式**：人工检查
- **依赖环境**：无
- **关键验证场景**：LLD 起草、LLD 验证、规则口径一致

## 量化验收标准（acceptance_criteria）
- [x] meta-dev 明确读取 Story/HLD/ADR/平台规则
- [x] meta-qa 明确读取测试设计/异常路径/回滚条件
- [x] 3 份 rules 文档与 LLD 方法口径一致

## 阻塞说明（如有）
已解决：以 Story / LLD / ADR / platform rules 为强输入，缺任一关键输入即阻断实现或验证。
