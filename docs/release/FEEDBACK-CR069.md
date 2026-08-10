---
project_id: meta-flow
cr_id: CR-069
release_artifact_profile: full
release_decision: NOT_READY
status: open-for-bounded-feedback
updated_at: '2026-08-10'
---

# CR-069 反馈回流与观察计划

| 信号 | 最小证据 | 路由 |
|---|---|---|
| provider receipt drift | typed reason、source/manifest/profile digest、mutation count | execution-control 修复切片 |
| consumer scanner finding | subject/edge/classification、canonical owner、source OID | owner/consumer cutover |
| writer bypass | operation、writer identity、authorization consumption、domain/coordination writes | P0 安全应急通道 |
| container 膨胀 | root/auxiliary/repair/Story/revision/QA-attempt/gate-interaction 计数 | admission hard gate |
| usage 超阈值 | reads/writes/checks/tokens、60/80/100% 状态 | cost controller |
| unknown leaf | leaf path、发现源、owner、retention class、first-seen stage | changed-leaf attribution |
| receipt 误失效 | old/new fingerprint、依赖层、实际失效测试层 | exact invalidation map |

## 后续机制

- intake 生成 live USAGE：60% 提醒、80% 停止新增范围、100% fail closed。
- 联合约束容器与内部复杂度：1 primary、0 auxiliary、0 repair、最多 3 Stories、2 次同根设计修订、2 次独立 QA、4 次人工 gate interaction、1 次 full suite。
- CP5 前完成 closed-world consumer/owner 扫描和 threat matrix；CP5/CP6/CP8 三次固化 changed-leaf inventory。
- mutation 只失效依赖该 source/profile 的验证层，避免无关全量重跑。

用户将更早看到范围/预算告警，并可能在 80% 阈值被要求缩小范围或建立后续单元；这会增加一次更早的范围选择，但显著降低一个 CR 长期循环设计—实现—QA 的概率。

反馈不得包含凭据、token、私钥、cookie、未脱敏日志、真实客户数据或 single-use authorization。外部项目、安装、生产运行和发布必须独立授权。
