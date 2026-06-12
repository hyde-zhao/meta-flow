---
project_id: "meta-flow"
scope: "workflow eval governance"
status: "healthy"
created_at: "2026-06-11T19:50:20+08:00"
---

# Eval Failure Backlog

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-11 | host-orchestrator | 新增 eval failure backlog |

## 状态枚举

| 状态 | 含义 |
|---|---|
| open | 新失败，尚未分流 |
| triaged | 已分类并有 owner |
| fixed | 已修复，等待复验 |
| waived | 已接受风险或明确豁免 |
| converted-to-cr | 已转正式 CR |
| closed | 已关闭 |

## 失败分类

| 类型 | 含义 |
|---|---|
| product-defect | 被测产物缺陷 |
| eval-defect | grader / runner 缺陷 |
| fixture-defect | fixture 或 case 数据缺陷 |
| environment | 环境缺失 |
| flaky | 不稳定失败 |
| expected-change | 预期变更导致基线漂移 |
| authorization-blocked | 需要运行授权、凭据或外部服务 |

## 当前失败

| Failure ID | 类型 | 状态 | 影响 | 证据 | 下一步 |
|---|---|---|---|---|---|
| N/A | N/A | closed | 无 open blocking failure | `docs/quality/EVAL-SUITE-HEALTH.md` | N/A |
