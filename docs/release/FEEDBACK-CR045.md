---
status: ready-for-cp8-review
version: "0.4.1"
release_artifact_profile: compact
release_decision: READY_WITH_RISK
---

# CR-045 Feedback

## 反馈回流入口

| Feedback ID | 类型 | 观察内容 | 分流 | follow-up tracking 候选 |
|---|---|---|---|---|
| CR045-FB-001 | defect | CR type / traits 对应的 CP applicability 或 required gate 错误 | route-plan regression / rework | yes |
| CR045-FB-002 | defect | N/A 被写成 WAIVED，或 waiver 缺少合法 reason / ref | CP result governance / rework | yes |
| CR045-FB-003 | defect | pass-like 结果保留 stale failure reason，或 BLOCKED 丢失授权 / health 原因 | state-transition regression / rework | yes |
| CR045-FB-004 | process-risk | CP2 / CP5 恢复历史被误写成实现前批准 | audit correction / host review | yes |
| CR045-FB-005 | hygiene | delivery guardrail 持续受到 ignored Python cache 影响 | repository hygiene | 仅重复出现时 yes |
| CR045-FB-006 | governance | dispatch ledger 可通过 schema，但缺少平台签发 receipt，仓库无法独立证明 agent/tool 调用真实性 | CR-A S01 producer contract | yes；不得倒填历史 receipt |

## 发布后观察计划

| Signal ID | 信号 | 方式 | 触发阈值 | 分流 |
|---|---|---|---|---|
| CR045-OBS-001 | route plan 与 gate profile 不一致 | `meta-flow route check` / CP0 result | 任意 1 个可复现错误 | defect |
| CR045-OBS-002 | N/A / WAIVED ledger 语义漂移 | CP result consistency / event check | 任意 1 个错误记录 | defect |
| CR045-OBS-003 | 自动推进过早停止或越过 required gate | state-transition check / user report | 任意 1 个可复现错误 | HIGH defect |
| CR045-OBS-004 | 授权或 workflow-health 原因被错误拒绝 / 接受 | exact decision × stop-reason matrix | 任意 1 个矩阵回归 | HIGH defect |
| CR045-OBS-005 | 测试缓存反复阻断 delivery guardrail | guardrail output | 清理后再次出现并阻断 | tech-debt candidate |
| CR045-OBS-006 | completed dispatch 只有自报 agent/tool 字段，没有平台 receipt | dispatch correlation / platform receipt checker | 任意 strict workflow 出现 1 次 | CR-A S01 governance |

## 台账边界

本文件只收集反馈，不创建正式 CR 或 follow-up 台账。标为候选的事项必须由 Host Orchestrator 完成冲突预检、正式分流和 ledger / index 同步后才能推进。CP8 readiness 不授权真实发布、push、runtime、外部调用或数据写入。
