---
status: release_candidate
version: "0.6.2"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.2 Migration

## 迁移结论

0.6.1 → 0.6.2 不批量改写历史 Work、Story、plan、ledger 或 receipt。新入口和 typed schema 是向后兼容新增；新写入必须走 native preflight/writer，历史材料继续只读。

| 对象 | 变化 | 兼容性 | 动作 |
|---|---|---|---|
| Work init | 新增 `work init-preflight` | compatible additive | init 前先执行零写模拟 |
| execution contract | init 时校验 typed ref/revision/root/slice/digest | fail-closed strengthening | 修正错误合同后再创建 Work |
| system namespace | receipt/failure/BLOCKER/HANDOFF/USAGE 不再消耗业务 scope | compatible fix | 不需要人工枚举 native writer 路径 |
| scope amendment | G0/G1 paused/blocked 可只增不减修订 | compatible additive | plan 后使用 exact authorization apply |
| ValidationPolicyV2 | environment/source manifest 参与 receipt 复用 | fail-closed strengthening | 漂移时接受 planner 降级 RUN |
| state projection | orphan FAIL 显式 warning/block | compatible safety fix | 补齐 observation 后 native reproject |

## 升级步骤

1. 从 `v0.6.2` Release 页获取 wheel、sdist、receipt 和 sidecar，校验 exact SHA-256。
2. 在隔离环境安装 exact wheel，运行 `meta-flow version --format json` 并确认 `READY`。
3. 对现有项目先运行只读 project/work preflight；不复用 0.6.1 环境下生成的 mutation plan 或 authorization。
4. 若存在非终态 transaction，使用原版本 inspect/recover 收敛后再升级。

## N/A

- 无数据库迁移、凭据变更或外部服务 cutover。
- 不自动修改消费者项目，不自动重编译历史计划。
- 0.6.2 typed version selection 不是兼容性 waiver，breaking/unknown 仍阻断。
