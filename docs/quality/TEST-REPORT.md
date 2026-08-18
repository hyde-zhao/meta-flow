---
status: pass_pending_artifact
version: "0.6.0-candidate"
release_decision: NOT_READY
updated_at: "2026-08-17T19:55:35+08:00"
---

# 0.6.0 Test Report

## 结论

R4/R4a 的 dotfile scope admission、原生 successor transaction 与 canonical 文档 tracking 均已通过；final detector requalification、repository hard gate、delivery guardrail 与完整回归也已收敛。当前测试结论为 `PASS`；clean provider receipt、artifact build 与 isolated canary 尚未完成，因此整体发布结论保持 `NOT_READY`，本报告本身不构成发布授权。

## 分层结果

| 层 | 结果 | 证据摘要 |
|---|---|---|
| 静态 | PASS | touched Python Ruff PASS；双仓 `git diff --check` PASS |
| scope/objective amendment | PASS | R4a 模型/真实事务组合 `47 passed`；支持安全根级 dotfile，拒绝绝对路径、`.`、`..`、穿越、双斜杠与反斜杠；R4 原生事务 COMMITTED |
| correction compatibility | PASS | `17 passed`；新 V2 correction manifest 被安装态 0.5.3 明确拒绝，当前 reader 保留 V1 历史读取 |
| summary / owner | PASS | 相关 projector、gate registry、ownership `38 passed`；consumer coverage `49/49` |
| digest / provider / lifecycle 组合 | PASS | `341 passed + 55 subtests`；sidecar/receipt 双文件恢复、symlink/outside/duplicate/tracked-generated 负向覆盖 |
| detector qualification | PASS | 连续两次 freeze scan 一致；189 files、407/407 classified、0 ambiguous；incremental dynamic 45/45 allowlisted、0 unresolved、findings=[]；detector tests `16 passed` |
| 完整回归（qualification 后） | PASS | `2635 passed + 716 subtests + 0 failed + 20 warnings`，用时 583.30 秒 |
| delivery guardrail（qualification 后） | PASS | exit 0、输出 `OK`；Ruff、uv lock、双仓 `git diff --check` 均 PASS |

## 发布层未闭项

测试与 detector 层没有未闭失败。剩余工作是 clean provider receipt、wheel/sdist、isolated canary 与人工发布门；它们属于 artifact/release readiness，不得用本报告的 PASS 代替。

## Warning 分类

- legacy receipt 缺 sidecar：一个版本的受控兼容 warning，不影响新 receipt fail-closed 合同；
- duplicate zip name：对抗性 fixture 的预期 warning；
- 没有凭据、网络、外部 consumer 或生产运行被测试进程授权。
