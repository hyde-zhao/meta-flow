---
name: change-impact-analysis
description: >-
  当用户发起需求变更、ISSUE 升级为结构性变更、或执行反馈驱动的设计调整时使用。
  触发词包括：需求变更、修改需求、变更影响、发起变更、CR。
  适用场景：元工作流任意阶段的变更管理。
argument-hint: "变更原因、变更类型（add/modify/delete）、影响范围描述"
user-invokable: true
status: draft
---

## 目标

受理变更请求，创建标准化的变更单 `CR-XXX.md`，执行五维度影响分析，判定回退阶段和审批要求，并更新 `STATE.md` 和 `CHANGELOG.md`。

## 适用范围

- 适用阶段：元工作流全部阶段（init 除外）
- 变更来源：用户直接提交、执行反馈驱动、问题工单升级
- 输出对象：`changes/CR-XXX.md`

## 前置条件

- [ ] `STATE.md` 已存在且当前阶段明确
- [ ] 变更原因和范围已由用户提供或可从 ISSUE/RUN-EXEC 推断
- [ ] `.fw-meta/templates/CR-TEMPLATE.md` 可用

## 执行约束

- 受理变更时必须先暂停当前阶段（设置 STATE.md 的 pending_action）
- 禁止跳过影响分析直接进入修改
- 影响分析必须覆盖全部五个维度
- CR 编号递增，不复用已有编号
- 同一高风险对象在一次交付窗口内只允许一次结构性变更（冷却机制）
- 同一 REQ-* 连续变更超过 3 轮时必须升级人工决策

## 五维度影响评估规则

| 维度 | 评估问题 | 影响时更新 |
|------|----------|-----------|
| 需求层 | 是否新增、删除或重定义 REQ-* | REQUIREMENTS.md |
| 场景层 | 是否改变测试矩阵覆盖范围 | SCENARIOS.yaml, TEST-MATRIX.md |
| 计划层 | 是否改变 Phase、Wave、任务依赖 | WORKFLOW-PLAN.yaml |
| 安全层 | 是否引入新的高风险动作或权限要求 | 需重新进入 Safety Reviewer |
| 交付层 | 是否需要重新生成交付物或回归子集 | OUTPUT/*.md, REGRESSION-TEST-SUBSET.yaml |

## 审批矩阵

| 风险级别 | 判定标准 | 处理方式 |
|----------|---------|---------|
| 低风险 | 文案修订、说明补充、非关键参数调整 | Orchestrator 自动批准 |
| 中风险 | 新增测试场景、调整执行顺序、修改验证标准 | 提交人工确认 |
| 高风险 | 修改安全边界、引入新权限、改变回滚策略 | 强制人工审批并重走安全审计 |

## Gotchas

- 变更单创建后必须先完成影响分析，给出 `impact_level: local/global` 和 `rollback_to` 结论，才能允许进入修改流程。过早放行会导致局部修改后上下游不一致
- 执行反馈驱动的变更（source 为 RUN-EXEC）通常需要同时更新 linked_issues 字段，确保 ISSUE 和 CR 双向关联

## 验收标准

- `changes/CR-XXX.md` 的 frontmatter 全部字段填写完整
- `impact_analysis` 五个维度都有 true/false 结论
- `rollback_to` 字段指向明确的阶段
- `STATE.md` 已更新 `active_change_requests` 列表
- `CHANGELOG.md` 已追加变更记录
