---
story_id: "UCD-02"
title: "use-case-discovery 模板与引用增强"
status: "verified"
priority: "P0"
wave: "W1"
depends_on: []
task_count: 3
created_at: "2026-04-23T11:37:06+08:00"
updated_at: "2026-04-23T11:47:36+08:00"
---

## 目标
补齐 `use-case-discovery` 的模板与引用，使治理字段、覆盖自检表和 8 维框架有稳定承载物。

## 开发上下文（dev_context）
- **输入文件**：`process/HLD.md`
- **输出文件**：`delivery/skills/use-case-discovery/references/8-dimensions-framework.md`、`delivery/skills/use-case-discovery/templates/USE-CASES-TEMPLATE.md`
- **设计约束**：frontmatter 必须容纳治理字段；覆盖自检表需可见；模板需与 `meta-pm` 规范兼容
- **平台目标**：全平台一致

### AI 可执行任务清单
| TASK-ID | 动作 | 目标文件 | 描述 |
|---|---|---|---|
| T1 | 创建/修改 | `delivery/skills/use-case-discovery/references/8-dimensions-framework.md` | 固化 D1-D8 维度与自定义维度说明 |
| T2 | 修改 | `delivery/skills/use-case-discovery/templates/USE-CASES-TEMPLATE.md` | 扩展治理字段 frontmatter |
| T3 | 修改 | `delivery/skills/use-case-discovery/templates/USE-CASES-TEMPLATE.md` | 增加治理附录与覆盖自检表 |

## 验证上下文（validation_context）
- **验证入口**：模板字段检查
- **验证方式**：人工检查
- **依赖环境**：无
- **关键验证场景**：mixed、治理字段、覆盖自检表

## 量化验收标准（acceptance_criteria）
- [x] 模板 frontmatter 包含 3 个治理字段
- [x] 8 维框架文档包含 D1-D8 与 Dx
- [x] 模板正文包含覆盖自检表与治理附录

## 阻塞说明（如有）
（无）
