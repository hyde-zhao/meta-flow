---
project_id: meta-flow
cr_id: CR-069
release_artifact_profile: full
release_decision: NOT_READY
status: prepared-not-executed
updated_at: '2026-08-10'
---

# CR-069 回滚方案

本文件只定义未来获得独立授权后的恢复动作；当前不授权回滚、历史重写、force push、tag 或 release。

| 触发条件 | 建议动作 | 必须保留 | 禁止动作 |
|---|---|---|---|
| CP8 仍为 NOT_READY | 保持 CR `blocked / NOT_READY / cp8_pending`，不撤销已验证产品提交；先修治理 closure | CP7、USAGE、unknown-leaf disposition、复盘 | 伪造 PASS/close |
| execution-control fail-open | 立即阻断新写入；建立有界修复单元，修复后重跑 targeted→compatibility→full | 原始 finding、receipt、source OID、mutation accounting | 风险接受安全缺陷 |
| scanner/receipt 误阻断 | 在隔离 fixture 复现，修正 canonical owner 后只重跑失效层 | manifest、profile、result digest | 恢复 caller self-sign |
| 已推送实现必须撤销 | 在独立授权下对 `4030ff1654d2e6f552f90bb6f23604117e41940d` 创建 `git revert` 提交并推送 | 原 commit、revert commit、验证 receipt | reset/rebase/force push |
| 仅发布文档错误 | 单独文档提交修正，不改产品 receipt/source | 文档 preimage 与修订原因 | 借文档提交修改产品 |

产品回滚至少执行 execution-control targeted、consumer scanner、closure、compatibility、full、Ruff、diff check 和 provider receipt 行为验证；过程状态只能通过 native lifecycle/status writer 更新。
