---
story_id: "UCD-03"
title: "UCD 上下游契约同步"
status: "verified"
priority: "P1"
wave: "W2"
depends_on: ["UCD-01", "UCD-02"]
task_count: 3
created_at: "2026-04-23T11:37:06+08:00"
updated_at: "2026-04-23T12:09:47+08:00"
---

## 目标
把 `use-case-discovery` 新增的治理字段与场景结构同步到 `meta-pm`、`requirement-extraction` 和 `skills/README`。

## 开发上下文（dev_context）
- **输入文件**：`process/HLD.md`、`delivery/skills/use-case-discovery/SKILL.md`、`delivery/skills/use-case-discovery/templates/USE-CASES-TEMPLATE.md`
- **输出文件**：`delivery/agents/meta-pm.md`、`delivery/skills/requirement-extraction/SKILL.md`、`delivery/skills/README.md`
- **设计约束**：meta-pm 必须明确先进入 Skill；requirement-extraction 必须直接消费正式 `USE-CASES.md`；README 映射必须更新
- **平台目标**：全平台一致

### AI 可执行任务清单
| TASK-ID | 动作 | 目标文件 | 描述 |
|---|---|---|---|
| T1 | 修改 | `delivery/agents/meta-pm.md` | 写清场景发现触发与治理字段产出 |
| T2 | 修改 | `delivery/skills/requirement-extraction/SKILL.md` | 写清对 `USE-CASES.md` 治理字段的消费 |
| T3 | 修改 | `delivery/skills/README.md` | 更新 Agent→Skill 与模板交叉引用关系 |

## 验证上下文（validation_context）
- **验证入口**：上述 3 个文件
- **验证方式**：人工检查
- **依赖环境**：无
- **关键验证场景**：meta-pm 触发链、requirement-extraction 消费链、README 注册关系

## 量化验收标准（acceptance_criteria）
- [x] `meta-pm.md` 显式提到治理字段输出
- [x] `requirement-extraction` 显式消费 `USE-CASES.md`
- [x] `delivery/skills/README.md` 中相关映射已刷新

## 阻塞说明（如有）
（无）
