---
status: draft
version: "1.0"
source_hld: "docs/design/HLD.md"
source_adr: "docs/design/ARCHITECTURE-DECISION.md"
confirmed_by: ""
confirmed_at: ""
---

# Feature Design Matrix

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | <date> | meta-se | 初始 Feature 设计适用性矩阵 |

## 适用性判定规则

| 维度 | 需要 Feature 设计的触发条件 | 可豁免条件 |
|---|---|---|
| 数据与状态 | 新增 / 修改核心对象、状态机、迁移、兼容策略 | 只读展示或无状态配置 |
| 接口与依赖 | 跨模块、外部接口、共享契约、依赖方向需要冻结 | 单文件局部改动且无新接口 |
| 权限与安全 | 权限边界、敏感信息、审计、运行授权 | 无权限变化且无敏感数据 |
| 运行与可靠性 | 并发、幂等、重试、性能、降级、回滚 | 无运行时风险扩展 |
| 多 Story 复用 | 多个 Story 共享同一能力边界或任务清单 | 单 Story 可直接用技术说明覆盖 |

## Feature 设计矩阵

| Feature ID | Feature / Epic | 来源 | 适用性 | 判定理由 | 需要产物 | 关联 Story | 建议 lld_policy | 重访条件 |
|---|---|---|---|---|---|---|---|---|
| FEAT-001 | <name> | BP- / HLD- / ADR- | required / waived / n/a | <reason> | DESIGN / TEST-PLAN / TASKS / none | STORY-001 | full-lld / technical-note / waived | <condition> |

## Story 下游消费表

| Story ID | feature_design_refs | lld_policy.required_level | trigger_reasons | 设计证据 | CP5 审查方式 |
|---|---|---|---|---|---|
| STORY-001 | docs/features/<feature>/DESIGN.md | full-lld / technical-note / waived | data / security / cross-module / external / concurrency / migration / low-risk | LLD / Story 技术说明 / waived reason | CP5 自动预检 + 批量人工确认 |

## 提前确认的关键决策

> 仅登记如果延后会显著增加返工成本、影响架构 / 安全 / 权限 / 外部接口 / 运行授权的关键决策。每项必须进入 `STATE.md.human_gate_decisions.pending_human_decisions[]` 或写明 N/A 原因。

| Decision ID | 决策类型 | 问题 | 推荐方案 | 备选方案 | 优劣摘要 | 影响 / 风险 | 回退 / 切换条件 | 状态 |
|---|---|---|---|---|---|---|---|---|
| DQ-FD-001 | architecture / security / implementation / runtime_authorization / risk_acceptance | <question> | <recommendation> | <alternative> | <pros-cons> | <impact-risk> | <rollback-switch> | open / resolved / n/a |

## 豁免与 N/A 说明

| Feature ID | 豁免 / N/A 原因 | 影响范围 | 风险接受 | 重访条件 | 责任方 |
|---|---|---|---|---|---|
| FEAT-XXX | <reason> | <scope> | accepted / not-needed | <condition> | <owner> |

## 自检

| 检查项 | 结果 | 证据 |
|---|---|---|
| 所有 Feature / Epic 均已判定 | PASS / FAIL | <evidence> |
| required Feature 均有产物计划或已生成 | PASS / FAIL | <evidence> |
| 每个 Story 均有 feature_design_refs 与 lld_policy | PASS / FAIL | <evidence> |
| 提前确认的关键决策已进入人工决策队列或 N/A | PASS / FAIL | <evidence> |
