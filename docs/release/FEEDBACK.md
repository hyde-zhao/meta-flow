---
project_id: "meta-flow"
release_scope: "workflow-eval-governance"
created_at: "2026-06-11T19:50:20+08:00"
---

# Feedback

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-11 | host-orchestrator | 新增 workflow eval governance 反馈入口 |

## 反馈分流

| 信号 | 分流 |
|---|---|
| eval schema 无法覆盖新 workflow 类型 | 创建新 CR，更新 `evals/contracts/*` |
| runner 无法解析复杂 YAML | 创建 runner CR，考虑引入正式 parser |
| external adapter 需要真实运行 | 创建 runtime_authorization CR 或 Spike |
| suite health 出现 blocking failure | 写入 `docs/quality/FAILURE-BACKLOG.md` 并路由回实现或评估修复 |

## 当前后续项

无 open follow-up candidate。
