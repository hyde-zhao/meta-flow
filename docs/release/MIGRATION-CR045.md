---
status: ready-for-cp8-review
version: "0.4.1"
release_artifact_profile: compact
release_decision: READY_WITH_RISK
---

# CR-045 Migration

## 迁移结论

CR-045 不需要数据、配置、安装路径或状态 schema 迁移。变更作用于新生成或新校验的 route plan、CP result 和 state transition；既有 checkpoint 与 ledger 历史保持原样，不得重写为新的 N/A / WAIVED 语义，也不得把恢复审批倒填到历史 CP6 之前。

| 对象 | 是否变化 | 兼容性 | 需要迁移 | 验证 / 处理 |
|---|---|---|---|---|
| `STATE.current.json` schema | 否 | compatible | 否 | 仅由受控 state transition writer 消费新路由语义 |
| route plan 内容 | 是 | compatible | 否 | 新生成计划使用 CR traits / gate profile；既有计划按其审计记录保留 |
| CP result 语义 | 是 | compatible | 否 | 新结果显式区分 N/A 与 WAIVED；不批量重写历史结果 |
| checkpoint / event ledger | 否 | compatible | 否 | append-only 历史不变 |
| 模板字段 / 配置格式 | 否 | N/A | 否 | 无动作 |
| 安装路径 / Agent frontmatter | 否 | N/A | 否 | 无动作 |
| Skill 输出格式 / 命令参数 | 否 | compatible | 否 | CLI 参数未变 |
| 数据存储 / 外部接口 | 否 | N/A | 否 | 无动作 |

未来若 route plan 或 CP result schema 本身发生版本升级、需要批量重算既有 CR，或要写回活动状态，则必须另开迁移范围并提供备份、dry-run、幂等与回滚证据。
