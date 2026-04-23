---
story_id: "RG-01"
title: "meta-po 评审协调核心"
status: "verified"
priority: "P0"
wave: "W2"
depends_on: ["UCD-01", "UCD-02"]
task_count: 4
created_at: "2026-04-23T11:37:06+08:00"
updated_at: "2026-04-23T12:09:47+08:00"
---

## 目标
为 `meta-po` 增加阶段出口文档评审协调能力：调度、聚合、升级仲裁与按 `governance_mode` 分流。

## 开发上下文（dev_context）
- **输入文件**：`process/HLD-review-gate.md`、`process/HLD.md`
- **输出文件**：`delivery/agents/meta-po.md`
- **设计约束**：不得自评；不得直接改目标文档；往返 >=3 自动升级；仅在评审通过后再决定是否进入人工确认
- **平台目标**：全平台一致

### AI 可执行任务清单
| TASK-ID | 动作 | 目标文件 | 描述 |
|---|---|---|---|
| T1 | 修改 | `delivery/agents/meta-po.md` | 增加 review coordinator 能力 |
| T2 | 修改 | `delivery/agents/meta-po.md` | 固化聚合与升级仲裁规则 |
| T3 | 修改 | `delivery/agents/meta-po.md` | 写清 `governance_mode` 消费逻辑 |
| T4 | 修改 | `delivery/agents/meta-po.md` | 写清 story-planning / story-execution 交接边界 |

## 验证上下文（validation_context）
- **验证入口**：`meta-po.md`
- **验证方式**：人工检查
- **依赖环境**：无
- **关键验证场景**：评审不通过、超时、升级仲裁、tool/skill 无人工确认

## 量化验收标准（acceptance_criteria）
- [x] `meta-po.md` 包含 review 协调流程
- [x] 严重/一般/轻微 聚合规则完整
- [x] `governance_mode` 分流逻辑完整
- [x] 升级仲裁阈值明确

## 阻塞说明（如有）
（无）
