---
status: pass_pending_artifact
version: "0.6.0-candidate"
release_decision: NOT_READY
updated_at: "2026-08-17T19:55:35+08:00"
---

# 0.6.0 Quality Review

## Findings

| ID | 严重度 | 状态 | 结论 |
|---|---|---|---|
| REV-060-001 | HIGH | CLOSED | 0.5.3 曾静默接受 V1 correction provenance；新 writer 改为 V2 manifest identity，真实旧 inspector 返回 `BLOCKED / INVALID` |
| REV-060-002 | HIGH | CLOSED | Work objective 固定 0.5.5；新增向后兼容的 scope-amend V2 typed objective replacement，R3 原生事务已收敛 Work/State/CURRENT |
| REV-060-003 | RELEASE BLOCKING | CLOSED | R4a 后重新冻结 source baseline；407/407 writer 全部分类、0 ambiguous，incremental dynamic 45/45 allowlisted、0 unresolved，guardrail 与完整回归恢复全绿 |
| REV-060-004 | RELEASE BLOCKING | OPEN | provider release receipt 需要 clean checkout；commit、build、canary、tag/release 均尚未授权或执行 |
| REV-060-005 | CONTRACT DEFECT | CLOSED | `ScopeAmendAuthorizationV1` 接受 `.gitignore`，但 `ScopeDeltaV1` 首字符规则误拒绝根级 dotfile；R4a 统一安全 leaf 语义并增加正负向/真实事务测试，R4 原生 successor 已 COMMITTED |

## 设计与实现审查

- preflight/apply、Work/State、summary/gate owner 和 digest/source-wheel-install 均使用单一 canonical core，不依赖相似规则复制；
- objective replacement 同时绑定 predecessor revision bytes、旧/新 objective、scope leaves、OID、dirty inventory、target/projection preimages 与唯一 validation graph；
- root dotfile scope amendment 只放宽安全 `add_owned_leaves`，其他 Story/dependency/acceptance token 语法不变；绝对路径、穿越、`.`、`..`、双斜杠与反斜杠继续 fail closed；
- correction 新输出对旧 reader fail closed，同时不改写 V1 热修历史；
- 过程证据复用一份累计 Implementation/Review 与 append-only revision/receipt，没有按每轮生成成套 context/handoff。

## 发布判断

产品代码无开放功能 HIGH/BLOCKER，R4/R4a 功能、原生事务、detector qualification、guardrail 与完整回归均 PASS。clean artifact 证据仍缺失，因此 `release_decision=NOT_READY`。只有在 clean wheel/sdist、provider receipt 与 isolated canary PASS 后，才能进入人工发布门。
