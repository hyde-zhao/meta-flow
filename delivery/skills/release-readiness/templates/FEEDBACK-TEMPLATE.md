---
status: draft
version: "1.0"
release_artifact_profile: compact
release_decision: NOT_READY
---

# Feedback

## 1. 反馈回流入口

| Feedback ID | 类型 | 来源 | 内容摘要 | 分流目标 | follow-up tracking 候选 | 状态 |
|---|---|---|---|---|---|---|
| FB-001 | defect / new-requirement / scenario-gap / tech-debt / incident | user / test / prod / review | <摘要，不复制长日志> | regression / backlog / scenarios / follow-up-tracking | yes / no | candidate |

## 2. 发布后观察计划

| Signal ID | 观察信号 | 观察方式 | 触发阈值 | 分流 |
|---|---|---|---|---|
| OBS-001 | 安装失败 | 用户反馈 / dry-run / issue | >=1 blocking | defect / follow-up |
| OBS-002 | Prompt / Agent 行为异常 | 用户反馈 / review | HIGH impact | CR candidate |
| OBS-003 | 平台差异问题 | Codex / Claude dry-run | reproducible | defect / regression |
| OBS-004 | guardrail 误报或漏报 | guardrail result / report | confirmed | follow-up |
| OBS-005 | 文档不可理解 | 用户反馈 | repeated | doc backlog |

## 3. 台账边界

`FEEDBACK.md` 是反馈回流入口，不是正式 follow-up tracking 台账。`follow-up tracking 候选=yes` 的条目必须由 CP8 分流写入 `process/changes/CR-*-FOLLOW-UP-TRACKING-YYYY-MM-DD.md`，并同步 `process/changes/CR-INDEX.yaml|json 与 process/state/CR-LEDGER.ndjson` 后，才可作为后续 CR 候选推进。

默认不生成独立 `POST-RELEASE-OBSERVATION.md`；仅 `release_artifact_profile=full` 或用户明确要求时，才把本文件的观察计划拆出为独立文档。
