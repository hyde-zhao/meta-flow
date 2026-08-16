---
status: draft
version: "1.1"
source_use_cases:
  - UC-WORK-PREFLIGHT
  - UC-SCOPE-AMENDMENT
  - UC-TYPED-REFS
  - UC-FULL-REGRESSION-SEMANTICS
  - UC-VALIDATION-REUSE
  - UC-UNREGISTERED-FAILURE-VISIBILITY
source_scenarios: [SCN-MF1-01, SCN-MF1-02, SCN-MF1-03, SCN-MF2-01, SCN-MF2-02, SCN-MF2-03, SCN-MF3-01, SCN-MF3-02, SCN-MF3-03, SCN-MF4-01, SCN-MF4-02, SCN-MF4-03, SCN-MF5-01, SCN-MF5-02, SCN-MF5-03, SCN-MF6-01, SCN-MF6-02, SCN-MF6-03]
source_requirements: [REQ-MF1-01, REQ-MF1-02, REQ-MF1-03, REQ-MF2-01, REQ-MF2-02, REQ-MF2-03, REQ-MF3-01, REQ-MF3-02, REQ-MF3-03, REQ-MF4-01, REQ-MF4-02, REQ-MF4-03, REQ-MF5-01, REQ-MF5-02, REQ-MF5-03, REQ-MF6-01, REQ-MF6-02, REQ-MF6-03]
confirmed_by: ""
confirmed_at: ""
formal_cp2_status: pending
---

# CR-071 Story Map

> 本文件是产品 outcome 规划，不是过程仓 Story 卡、技术拆分、HLD 或 LLD。

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 | 来源 |
|---|---|---|---|---|
| 1.0 | 2026-08-15 | meta-pm | 建立 MF-1～MF-6 产品 Story Map | USE-CASES / REQUIREMENTS / SCENARIOS |
| 1.1 | 2026-08-15 | meta-pm | 将 CP2 revision 2 六项 delta 收敛到既有 12 个产品 outcome Story | 保留 Story ID；技术文件仅留在 CP4 inventory |

## 用户活动

| Activity ID | 用户活动 | 目标用户 | 业务目标 | 来源 |
|---|---|---|---|---|
| ACT-01 | 在 apply 前评估 Work 初始化 | P-01、P-02 | 让机械错误在零写阶段可见 | UC-WORK-PREFLIGHT |
| ACT-02 | 在审计链内修订 scope | P-01、P-02、P-03 | 安全增加范围而不改写历史 | UC-SCOPE-AMENDMENT |
| ACT-03 | 读取与迁移跨仓引用 | P-01、P-02、P-03 | 消除仓角色和前缀歧义 | UC-TYPED-REFS |
| ACT-04 | 决定分层回归执行策略 | P-02、P-03 | 消除 full regression 禁令误读 | UC-FULL-REGRESSION-SEMANTICS |
| ACT-05 | 判断验证证据是否可复用 | P-02、P-03 | 只复用身份稳定的验证层 | UC-VALIDATION-REUSE |
| ACT-06 | 判断状态投影是否真实健康 | P-02、P-03 | 让未登记失败和漂移可见 | UC-UNREGISTERED-FAILURE-VISIBILITY |

## 用户任务与 Story

| Story ID | Activity ID | 用户任务 | Story | 优先级 | 验收摘要 | 来源 |
|---|---|---|---|---|---|---|
| ST-MF1 | ACT-01 | 预演完整初始化 | 作为 Work 维护者，我希望 preflight 与 apply 从同一校验决策源判断输入，以便在零写阶段一次发现错误且不会因入口不同得到相反结论 | P0 | 同快照 normalized decision graph 100% 一致；preflight mutation=0 | UC-WORK-PREFLIGHT；REQ-MF1-01～03；SCN-MF1-01 |
| ST-MF2 | ACT-02 | 创建受控范围 revision | 作为 Host Orchestrator，我希望 revision>1 在合法接纳 predecessor/inventory 后才创建 append-only scope revision，以便扩大范围时保留授权和 supersession 审计链 | P0 | BL-001 admission 先通过；旧 revision 不变，新 revision 含 authz/classification/invalidation | UC-SCOPE-AMENDMENT；REQ-MF2-01～03；SCN-MF2-01 |
| ST-MF3 | ACT-03 | 解析 canonical typed ref | 作为工作流维护者，我希望兼容 reader 能读旧引用而所有新写入只产生 canonical 引用，以便跨仓对象不会被隐式误解并可量化退役旧 reader | P0 | writer v1=0、residual=0、ambiguous/misread=100%，两快照 v1 observed=0 才可提议退役 | UC-TYPED-REFS；REQ-MF3-01～03；SCN-MF3-01/03 |
| ST-MF4 | ACT-04 | 读取无禁令歧义的回归策略 | 作为验证编排者，我希望 canonical 字段只表达默认执行策略且兼容窗口有量化出口，以便 required full regression 不被误跳过 | P0 | canonical/legacy 归一化后分层计划唯一，writer 只写 canonical | UC-FULL-REGRESSION-SEMANTICS；REQ-MF4-01～03；SCN-MF4-01/03 |
| ST-MF5 | ACT-05 | 复用语义稳定验证层 | 作为质量审查者，我希望 receipt 复用按 canonical semantic identity 判断，以便机器或字符串偶然差异不被误拒，而安全漂移绝不复用 | P0 | 等价 fixture 误拒=0；安全相关非等价漂移拒绝=100% | UC-VALIDATION-REUSE；REQ-MF5-01～03；SCN-MF5-01/02 |
| ST-MF6 | ACT-06 | 查看并恢复真实失败健康状态 | 作为 Host Orchestrator，我希望缺失归属证据时状态阻断、补证后一次重投影自动收敛，以便不会靠手改派生状态误推进 | P0 | 缺证 fail closed；补证后一次 reprojection 退出阻断并使 state/current 一致 | UC-UNREGISTERED-FAILURE-VISIBILITY；REQ-MF6-01～03；SCN-MF6-01/03 |

## 负向 / 边界 Story

| Story ID | 触发场景 | 用户可见结果 | 验收摘要 | 来源 |
|---|---|---|---|---|
| ST-N-MF1 | stale revision、scope/budget 错误或 obligation 缺失 | preflight/apply shared core 返回相同失败项，预检没有任何治理写入 | normalized decision 一致且 bytes/digest 不变 | SCN-MF1-02、SCN-MF1-03；REQ-MF1-01～03 |
| ST-N-MF2 | BL-001 admission 缺失、stale preimage、未知路径或授权不足 | MF-2 实现/E2E 或 scope-amend 被拒绝且不产生 partial revision | fail closed，给出 predecessor inventory、重新 plan 或授权入口 | SCN-MF2-02、SCN-MF2-03；REQ-MF2-01～03 |
| ST-N-MF3 | unknown role、前缀矛盾或 v1 边界 | 返回明确兼容/迁移诊断，不猜默认仓 | ambiguous/misread 检出=100%，量化门槛未达不得提议 reader 退役 | SCN-MF3-02、SCN-MF3-03；REQ-MF3-01～03 |
| ST-N-MF4 | legacy 字段存在禁令误读风险 | 仍保留 required full 层或明确阻断 | canonical/v1 决策等价且 provenance 可见 | SCN-MF4-02、SCN-MF4-03；REQ-MF4-01～03 |
| ST-N-MF5 | 安全相关 semantic identity drift、缺证据或 partial receipt | 拒绝受影响层并给出最小重跑计划 | 安全漂移拒绝=100%，不用旧 PASS 掩盖失败 | SCN-MF5-02、SCN-MF5-03；REQ-MF5-01～03 |
| ST-N-MF6 | unknown failure ownership 后补齐有效证据 | 未知时降级，补证后一次 reprojection 收敛，稳定时语义 no-op | 不伪造绿色、不手改派生状态；state/current 事实一致 | SCN-MF6-02、SCN-MF6-03；REQ-MF6-01～03 |

## 非目标

- 不在产品 Story 中指定 Python 模块、函数、数据库、文件 owner 或 merge order。
- 不在 CP2 前生成过程仓 Story 卡、Feature DESIGN、HLD 或 LLD。
- 不把真实运行、外部写入、安装或发布包装成产品验收动作。

## 追溯矩阵

| 来源 ID | 覆盖 Story | 覆盖状态 | 缺口 / 说明 |
|---|---|---|---|
| UC-WORK-PREFLIGHT / REQ-MF1-01～03 / SCN-MF1-01～03 | ST-MF1, ST-N-MF1 | covered | 无产品级缺口 |
| UC-SCOPE-AMENDMENT / REQ-MF2-01～03 / SCN-MF2-01～03 | ST-MF2, ST-N-MF2 | covered | 无产品级缺口 |
| UC-TYPED-REFS / REQ-MF3-01～03 / SCN-MF3-01～03 | ST-MF3, ST-N-MF3 | covered | read-old/write-new 与量化门槛待 formal CP2 冻结 |
| UC-FULL-REGRESSION-SEMANTICS / REQ-MF4-01～03 / SCN-MF4-01～03 | ST-MF4, ST-N-MF4 | covered | 具体 successor 字段名留给 CP3 |
| UC-VALIDATION-REUSE / REQ-MF5-01～03 / SCN-MF5-01～03 | ST-MF5, ST-N-MF5 | covered | 无产品级缺口 |
| UC-UNREGISTERED-FAILURE-VISIBILITY / REQ-MF6-01～03 / SCN-MF6-01～03 | ST-MF6, ST-N-MF6 | covered | 无产品级缺口 |
