---
story_id: "RG-02"
title: "review 产物协议与静态前置检查"
status: "verified"
priority: "P1"
wave: "W3"
depends_on: ["RG-01"]
task_count: 4
created_at: "2026-04-23T11:37:06+08:00"
updated_at: "2026-04-23T13:30:00+08:00"
---

## 目标
为 review gate 补齐 findings/summary 产物协议，并提供轻量静态前置检查脚本。

## 开发上下文（dev_context）
- **输入文件**：`process/HLD-review-gate.md`、`process/PLATFORM-INSTALL-SPEC.md`
- **输出文件**：`delivery/skills/review-artifact-protocol/templates/REVIEW-FINDINGS-TEMPLATE.md`、`delivery/skills/review-artifact-protocol/templates/REVIEW-SUMMARY-TEMPLATE.md`、`delivery/skills/review-artifact-protocol/scripts/validate_review_artifact.py`
- **设计约束**：模板需服务仓库运行态；脚本只做机械性检查；不得替代语义评审
- **平台目标**：仓库运行态优先

### AI 可执行任务清单
| TASK-ID | 动作 | 目标文件 | 描述 |
|---|---|---|---|
| T1 | 创建 | `delivery/skills/review-artifact-protocol/templates/REVIEW-FINDINGS-TEMPLATE.md` | 固化 findings 字段 |
| T2 | 创建 | `delivery/skills/review-artifact-protocol/templates/REVIEW-SUMMARY-TEMPLATE.md` | 固化 summary 结构 |
| T3 | 创建 | `delivery/skills/review-artifact-protocol/scripts/validate_review_artifact.py` | 校验 frontmatter / 章节 / 锚点 |
| T4 | 修改 | `delivery/agents/meta-po.md` 或相关说明 | 接入模板与静态检查调用说明 |

## 验证上下文（validation_context）
- **验证入口**：模板字段、脚本参数、示例文档
- **验证方式**：人工检查 + 脚本 dry-run
- **依赖环境**：Python/uv
- **关键验证场景**：缺字段、版本回退、锚点缺失

## 量化验收标准（acceptance_criteria）
- [x] findings 模板包含 reviewer/lane/artifact/severity/rule_ref/evidence
- [x] summary 模板包含聚合结论与往返轮次
- [x] 静态检查脚本覆盖 frontmatter/章节/锚点 3 类问题

## 阻塞说明（如有）
已解决：采用 `delivery/skills/review-artifact-protocol/` 作为共享评审资产目录，并随 Skill 同树安装。
