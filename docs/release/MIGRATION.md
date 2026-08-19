---
status: frozen_candidate
version: "0.6.1"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.1 Migration

## 迁移结论

0.6.0 → 0.6.1 不要求批量改写历史 Work、Story、plan、ledger 或 receipt。新增 compiler、closure、cost、SemVer 与 release-order 合同采用向后兼容的新入口；新写入必须使用 canonical compiler/typed writer，历史材料继续只读。

## 兼容矩阵

| 对象 | 变化 | 兼容性 | 迁移动作 |
|---|---|---|---|
| 公共 CLI | 新增 `package compile/closure-build/cost-report/semver-decide/release-*` | compatible additive | 无；按需采用 |
| Plan schema / canonical IR | 新增机器权威表示 | compatible read / strict new write | 新 plan 通过 compiler 生成；handwritten plan 不作为 authority |
| Story contract | 增加 production entrypoint reachability | fail-closed strengthening | helper-only Story 补齐生产入口证据 |
| closure/ledger/receipt | 新增 affected closure 与三真相归一 | compatible additive | 不改写旧记录；新记录走 native writer |
| usage stage | routine `clarification` 与 aliases 归一 | compatible fix | 无批量迁移 |
| SemVer gate | 0.6.1 使用一次性 typed bootstrap | one-time initialization | 0.6.1 后不得复用 bootstrap |
| release-order state | 新增有序状态机与单次计数 | fail-closed release gate | 后续发布必须按 canonical action 顺序 |

## 升级步骤

1. 核验 GitHub Release 上 wheel、sdist、receipt 与 sidecar 的 exact digest；当前尚未授权远端发布，因此本步骤暂不执行。
2. 在隔离环境安装 exact wheel，运行 `meta-flow version --format json` 并确认 `READY`。
3. 先以只读/plan 模式验证现有项目；不要复用旧版本生成的 mutation plan 或 authorization。
4. 新建 plan 时使用 Plan Compiler；仅在 exact scope、ownership 与 closure 验证通过后 apply。
5. 若存在非终态事务，停止升级并使用原版本 native inspect/recover。

## N/A

- 无数据库迁移、凭据变更或外部服务 cutover。
- 不自动修改消费者项目，不自动重编译历史计划。
- 版本号 bootstrap 不是兼容性 waiver；breaking/unknown 仍阻断。
