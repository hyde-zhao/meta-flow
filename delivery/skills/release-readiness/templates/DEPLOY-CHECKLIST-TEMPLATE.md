---
status: draft
version: "1.0"
release_artifact_profile: compact
release_decision: NOT_READY
---

# Deploy Checklist

> 影响面驱动：只检查 `process/release/RELEASE-CONTEXT.yaml` 中受影响的平台、组件和 scope；不复制命令长日志。

## 1. 发布前输入检查

| 输入 | 状态 | 证据路径 | 说明 |
|---|---|---|---|
| Release Context Capsule | PASS / FAIL | `process/release/RELEASE-CONTEXT.yaml` | <说明> |
| TEST-REPORT | PASS / PASS_WITH_RISK / BLOCKED / N/A | `docs/quality/TEST-REPORT.md` | <说明> |
| REVIEW | PASS / RISK / BLOCKED / N/A | `docs/quality/REVIEW.md` | <说明> |
| BLOCKER findings | 0 / N | <evidence> | <说明> |
| HIGH findings | 0 / N / accepted | <risk id> | <说明> |

## 2. 发布候选快照

| 检查项 | 状态 | 证据 / 摘要 |
|---|---|---|
| 变更范围清楚 | PASS / FAIL | <diff summary / path> |
| 未跟踪文件已分类 | PASS / FAIL / N/A | release-content / temp / user-file / ignored |
| 缓存与临时文件清理 | PASS / FAIL | <evidence> |
| 敏感信息检查 | PASS / FAIL | <evidence> |

## 3. 安装 / 升级 / 幂等验证矩阵

| 平台 | 组件 | Scope | 场景 | 是否适用 | 验证命令 / 方法 | 结果 | N/A 原因 |
|---|---|---|---|---|---|---|---|
| Codex | agents / skills / rules / full | project / user | fresh install dry-run | yes / no | `<command or method>` | PASS / FAIL / N/A | <reason> |
| Claude Code | agents / skills / rules / full | project / user | upgrade / repeated dry-run / idempotency | yes / no | `<command or method>` | PASS / FAIL / N/A | <reason> |
| All | install / uninstall | project / user | rollback / uninstall | yes / no | `<command or method>` | PASS / FAIL / N/A | <reason> |

## 4. 平台和权限边界

| Check ID | 检查项 | 状态 | 证据 / 说明 | 阻断等级 |
|---|---|---|---|---|
| DEP-001 | 平台路径符合 contract | pending | <evidence> | BLOCKING |
| DEP-002 | Claude direct ask tools 权限正确 | pending / N/A | <evidence> | REQUIRED |
| DEP-003 | Codex 不包含 Claude-only schema | pending / N/A | <evidence> | REQUIRED |
| DEP-004 | 不覆盖用户本地配置，或有明确提示 | pending / N/A | <evidence> | BLOCKING |
| DEP-005 | 回滚方案已确认 | pending | `docs/release/ROLLBACK.md` | REQUIRED |

## 5. 发布结论

| 项目 | 内容 |
|---|---|
| release_artifact_profile | minimal / compact / full |
| release_decision | READY / READY_WITH_RISK / NOT_READY / RELEASED / FAILED |
| 阻断项 | <count / list> |
| 风险接受项 | <risk id / N/A> |

## 6. 不授权项

| Item ID | 不授权操作 | 原因 | 需要的独立授权 |
|---|---|---|---|
| NA-001 | <publish / live / data write / external call> | <原因> | <授权条件> |
