---
status: draft
version: "1.0"
release_artifact_profile: compact
release_decision: NOT_READY
---

# Release Notes

> Compact-first：面向用户说明变化，不复制文件 diff、长日志或上游报告全文。

## 1. 摘要

| 项目 | 内容 |
|---|---|
| 版本 | vX.Y.Z |
| 发布结论 | READY / READY_WITH_RISK / NOT_READY / RELEASED / FAILED |
| 发布范围 | <一句话摘要> |
| 主要风险 | <risk id / N/A> |

## 2. 版本号决策

| 项目 | 内容 |
|---|---|
| 当前版本 | vX.Y.Z |
| 目标版本 | vA.B.C |
| 变更类型 | MAJOR / MINOR / PATCH / alpha / beta / rc |
| 兼容性 | breaking / compatible / unknown |
| 推荐原因 | <一句话原因> |

## 3. 新增能力 / 用户可见变化

| Change ID | 内容 | 影响用户 | 来源 |
|---|---|---|---|
| REL-001 | <变化> | <用户> | ST- / REQ- / CR- |

## 4. 行为变化 / 修复问题

| Change ID | 类型 | 内容 | 用户影响 |
|---|---|---|---|
| REL-002 | behavior-change / fix | <内容> | <影响> |

## 5. 破坏性变更

| Breaking ID | 是否存在 | 内容 | 迁移引用 |
|---|---|---|---|
| BR-001 | yes / no | <内容或 N/A> | `docs/release/MIGRATION.md` |

## 6. 安装与升级

| 场景 | 方式 | 验证证据 |
|---|---|---|
| 安装 / 升级 / dry-run | <摘要> | `docs/release/DEPLOY-CHECKLIST.md` |

## 7. 迁移说明

| 是否需要迁移 | 影响对象 | 说明 |
|---|---|---|
| yes / no | <对象或 N/A> | `docs/release/MIGRATION.md` |

## 8. 已知问题与风险

| Risk ID | 严重度 | 状态 | 处理 |
|---|---|---|---|
| R-001 | HIGH / MEDIUM / LOW | open / accepted / closed | <处理方式> |

## 9. 回滚方式

| 回滚触发 | 回滚入口 | 说明 |
|---|---|---|
| <条件> | `docs/release/ROLLBACK.md` | <摘要> |

## 10. 参考链接

| 类型 | 路径 |
|---|---|
| Release Context | `process/release/RELEASE-CONTEXT.yaml` |
| Test Report | `docs/quality/TEST-REPORT.md` |
| Review | `docs/quality/REVIEW.md` |
