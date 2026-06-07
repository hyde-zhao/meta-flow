---
status: draft
version: "1.0"
release_artifact_profile: compact
release_decision: NOT_READY
---

# Rollback

## 1. 回滚摘要

| 项目 | 内容 |
|---|---|
| 回滚目标版本 | vX.Y.Z |
| 回滚范围 | <files / components / config / state> |
| 是否涉及数据恢复 | yes / no |
| 是否存在不可回滚项 | yes / no |
| 决策人 | human / owner |

## 2. 回滚触发条件

| Trigger ID | 条件 | 监控 / 证据 | 决策人 |
|---|---|---|---|
| RB-T01 | <条件> | <证据路径或摘要> | human |

## 3. 回滚步骤

| Step | 操作 | 前置条件 | 验证 | 风险 |
|---|---|---|---|---|
| 1 | <操作> | <precondition> | <verify> | <risk> |

## 4. 回滚验证

| 验证项 | 方法 | 结果 |
|---|---|---|
| 安装 / 加载恢复 | <command or method> | PASS / FAIL / N/A |
| 状态 / 配置恢复 | <method> | PASS / FAIL / N/A |

## 5. 不可回滚项

| 对象 | 是否存在 | 原因 | 处理 |
|---|---|---|---|
| <object> | yes / no | <reason> | <mitigation> |
