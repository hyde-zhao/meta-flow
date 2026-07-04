---
status: draft
version: "1.0"
release_artifact_profile: compact
release_decision: NOT_READY
---

# Migration

## 1. 迁移结论

| 项目 | 内容 |
|---|---|
| 是否需要迁移 | yes / no |
| 是否自动迁移 | yes / no / N/A |
| 是否保留兼容路径 | yes / no / N/A |
| 是否可逆 | yes / no / N/A |
| CP8 fact_diff 迁移影响 | `process/release/RELEASE-CONTEXT.yaml#fact_diff` / N/A |

## 2. 兼容性判断表

| 对象 | 是否变化 | 兼容性 | 需要迁移 | 验证方式 | 回滚方式 |
|---|---|---|---|---|---|
| `STATE.md` schema | yes / no | compatible / breaking / N/A | yes / no | <verify> | <rollback> |
| 模板字段 | yes / no | compatible / breaking / N/A | yes / no | <verify> | <rollback> |
| 配置格式 | yes / no | compatible / breaking / N/A | yes / no | <verify> | <rollback> |
| 安装路径 | yes / no | compatible / breaking / N/A | yes / no | <verify> | <rollback> |
| Agent frontmatter | yes / no | compatible / breaking / N/A | yes / no | <verify> | <rollback> |
| Skill 输出格式 | yes / no | compatible / breaking / N/A | yes / no | <verify> | <rollback> |
| 命令参数 | yes / no | compatible / breaking / N/A | yes / no | <verify> | <rollback> |
| 数据存储结构 | yes / no | compatible / breaking / N/A | yes / no | <verify> | <rollback> |

## 3. 迁移步骤

| Step | 操作 | 前置条件 | 验证 | 回退 |
|---|---|---|---|---|
| 1 | <操作或 N/A> | <precondition> | <verify> | <rollback> |

## 4. N/A 说明

| 项目 | 原因 | 后续触发条件 |
|---|---|---|
| <对象> | <若无迁移，写短原因> | <未来什么条件下需要迁移> |
