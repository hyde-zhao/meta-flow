---
status: ready_for_publication
version: "0.6.5"
base_version: "0.6.3"
release_artifact_profile: full
release_decision: READY_WITH_RISK
---

# Meta Flow 0.6.5 发布说明

## 摘要

0.6.5 将 CR-076 的分发/发布能力与 CR-077 的治理等级拆分合并为一个公开版本。治理风险等级升级为 V2：高风险变更默认进入轻量 G2；只有用户显式要求完整 LLD 时才进入 G3。历史 V1 G2 在读取时继续等价于完整 G3，不批量改写历史对象。

用户明确选择 0.6.5；公开版本 0.6.4 被跳过，不存在 0.6.4 release 或兼容性基线。由于新增公共治理 profile、schema 和 CLI 行为，常规 SemVer 更适合 minor 版本；本次 0.6.5 是用户显式选择的非 precedent 风险接受，不应被后续发布自动复用。

## 用户可见变化

- 新增 `GovernanceRiskProfile V2`：`G0/G1/G2/G3`。
- 原 G2 完整设计路径迁移为 G3；V1 G2 兼容读取为 effective G3。
- 新 G2 在 CP4/CP5 只要求每个 Story 的 `ScopeGoalNoteV1`，确认范围、目标、验收边界和文件影响。
- 无架构变化的 G2 可使用 CP3-lite；存在架构影响时恢复 CP3 人工复核，但不会擅自升级 G3。
- 公共契约、安全、凭据、生产写、不可逆迁移、跨设备授权和分布式事务等 consent trigger 会 fail closed，等待用户决定是否进入 G3。
- G3 选择绑定 CR、source OID、route revision、选择记录与授权文件摘要；任一漂移都会使旧验证身份失效。
- pending gate 由 route、当前 result head 和与该 head 精确绑定的 launch/approval 推导，旧审批不能批准新结果，也不能越过缺失的 CP6/CP7。
- publication operation 的 `G0/G1/G2` 风险等级保持独立三档，不受治理 G3 命名空间影响。
- 分发能力包含 release asset discovery、bundle identity、安装/升级/回滚、consumer acceptance 导入和 publication close 前摘要验证。

## Provider identity

0.6.5 将固定 activation receipt 从 v10 轮换到 v11；v1-v10 bytes 保持不变。v11 绑定当前 execution-control source owners 和本候选验证摘要。缺少匹配的 native authority chain 时，运行时 materializer 保持 fail-closed，不能在其他 checkout 重新生成同一 receipt。

## 兼容性与迁移

- 无数据库、凭据或生产数据迁移。
- V1 G2 不改写；读取时派生为 G3。
- 新建对象显式写 `risk_profile_schema_version=2`。
- 依赖旧“G2=完整 LLD”文本判断的外部自动化必须改为读取 schema version 和 effective profile。
- G0/G1 序列化继续保持旧形状，避免无关消费者漂移。

## 治理兼容面

- **Governance Truth Map / Retention Policy**：本版本继续以 canonical truth map 与 retention policy 约束治理事实来源和默认上下文保留；`cr_type`、概念所有权及 `conflict_keys` 的既有语义不变。
- **Context sufficiency / read expansion governance**：deny-default 读取仍通过 `READ-EXPANSION-LEDGER` 记录扩读原因；`output profile budgets` 继续限制交接摘要、检查点摘要和设计摘要的输出规模。
- **Failure routing / waiver governance**：失败路由继续由 `FAILURE-ROUTING.json` 决定，豁免由 `WAIVER-POLICY.json` 约束；安全、授权、真实内容失败等不可豁免项目不会因 G2 轻量设计而降级为 PASS。

## 验证摘要

- CR-077 专项矩阵：62 个用例，覆盖旧版兼容、默认 G2、显式 G3、scope-goal-note、架构/consent 分流、状态前沿和 publication 命名空间隔离。
- 专项与兼容回归：172 passed，8 subtests passed。
- 冻结后的最终无排除全量回归：3590 passed，728 subtests passed；另有 v11 receipt 与 detector 后置门联合验证 34 passed。
- Ruff 与 `git diff --check` 通过。

## 已知边界

- `host-injection` 是应用层可信边界，不是对本机恶意进程的密码学身份认证；具备过程仓写权限的恶意主体不在本版本威胁模型内。
- 0.6.5 不上传 PyPI 或其他 package registry；官方资产以 GitHub Release 的 wheel、sdist、receipt 和 sidecar 为准。

## 安装

从 `v0.6.5` GitHub Release 下载并校验以下四项资产后安装 exact wheel：

- `meta_flow-0.6.5-py3-none-any.whl`
- `meta_flow-0.6.5.tar.gz`
- `ProviderArtifactReceiptV1.json`
- `ProviderArtifactReceiptV1.digest-policy.json`

不得从 checkout 临时重建后冒充发布资产。

## 回滚

回滚目标为已发布的 0.6.3 exact assets。回滚只切换安装资产和 provider receipt，不删除历史对象、授权、receipt 或 append-only evidence。详见 `docs/release/ROLLBACK.md`。
