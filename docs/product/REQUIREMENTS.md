---
status: draft
version: "1.1"
confirmed: false
confirmed_by: ""
confirmed_at: ""
ready_for_design: false
source_change: "CR-071"
source_use_cases:
  - UC-WORK-PREFLIGHT
  - UC-SCOPE-AMENDMENT
  - UC-TYPED-REFS
  - UC-FULL-REGRESSION-SEMANTICS
  - UC-VALIDATION-REUSE
  - UC-UNREGISTERED-FAILURE-VISIBILITY
total_requirements: 18
blocking_open_questions: 0
formal_cp2_status: pending
---

# CR-071 结构化需求

## 来源与治理上下文

| 字段 | 值 |
|---|---|
| 主输入 | `docs/product/USE-CASES.md` |
| 变更来源 | `process/changes/CR-071.md`、`process/works/CR-071-R2/REQUEST.md` |
| 目标产物类型 | `mixed`（tool/CLI、schema/typed contract、workflow/projection） |
| 治理方式 | `review-gated` / `strict` |
| 当前判定 | 内容缺口为 0；因 CP2 人工批准尚未发生，`ready_for_design=false` |

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 | 文档处理方式 |
|---|---|---|---|---|
| 1.0 | 2026-08-15 | meta-pm | 为 MF-1～MF-6 建立 18 条初始需求 | 按 CR-071 决策新增，不覆盖历史对象 |
| 1.1 | 2026-08-15 | meta-pm | 在原 18 个 ID 上吸收 CP2 revision 2 六项 review delta | 增量修订；不新增 MF、REQ 或正式批准 |

## 需求条目

| ID | 类型 | 需求描述 | 优先级 | 验收条件 | 来源 |
|---|---|---|---|---|---|
| REQ-MF1-01 | 功能 | 系统必须提供 `work init-preflight`，通过与 apply 共用的单一 validation core/decision graph 模拟成功和失败两类完整 Work 生命周期且不执行 apply | P0 | Given 同一合法或非法快照，When 分别进入 preflight/apply 校验路径，Then normalized item、decision 与 error graph 一致；preflight 的 release/process/state/ledger mutation 均为 0 | UC-WORK-PREFLIGHT；CR-071 AC-1；REV-02 |
| REQ-MF1-02 | 约束 | preflight/apply 必须共享 typed refs、revision、scope closure、budget、lifecycle I/O 与 on-touch obligations 的校验规则；仅 orchestration/presentation 可不同 | P0 | Given 任一校验项无效，When 经两个入口调用 shared core，Then 返回同一确定 BLOCKED/FAIL item 和证据，且不得维护重复规则集 | UC-WORK-PREFLIGHT；CR-071 AC-1；REV-02 |
| REQ-MF1-03 | 非功能 | 同一输入快照的 preflight 结果必须可重复，并证明成功/失败路径均为零写 | P1 | Given 相同 OID/preimage 和输入，When 重复执行两次，Then item 集合、计划写集合与 result digest 一致且 mutation=0 | UC-WORK-PREFLIGHT；SM-01 |
| REQ-MF2-01 | 功能 | 系统必须通过 `scope-amend` 创建 append-only scope revision，禁止原地扩大旧 revision；BL-001 revision>1 legal supersession admission 是 MF-2 enabling prerequisite | P0 | Given predecessor/inventory 已确定且 admission 通过、active Work 与合法 delta，When amend 成功，Then 旧 revision bytes 不变且新 revision 明确 supersedes predecessor | UC-SCOPE-AMENDMENT；CR-071 AC-2；BL-001；REV-01 |
| REQ-MF2-02 | 约束 | 每次 scope amendment 必须重新分类、重新授权并失效受影响的 receipt 与 gate evidence | P0 | Given scope delta 影响既有证据，When 计划 amend，Then 输出 reclassification/authz 结论与精确 invalidation set；缺任一结论不得 apply | UC-SCOPE-AMENDMENT；CR-071 AC-2 |
| REQ-MF2-03 | 非功能 | revision>1 supersession admission、revision/preimage/authz/scope 任一不一致时必须 fail closed 且保持 mutation=0 | P1 | Given predecessor/inventory admission 未证明、stale revision、未知路径或缺少 typed authorization，When 执行 MF-2 实现/E2E 或 amend，Then 返回拒绝原因且不创建 partial revision | UC-SCOPE-AMENDMENT；RISK-SCOPE-WIDENING；REV-01 |
| REQ-MF3-01 | 功能 | typed ref 必须显式携带 release/process repository role 与 logical namespace | P0 | Given 分别指向 release 和 process 的对象，When 解析 ref，Then 输出可区分的 repository role、canonical logical ref 和 object kind | UC-TYPED-REFS；CR-071 AC-3 |
| REQ-MF3-02 | 约束 | 相邻 ref 字段必须使用统一前缀语义，禁止一个字段保留 `process/` 而另一个隐式去前缀 | P0 | Given 同一 logical object 出现在相邻 schema 字段，When 做 contract check，Then 两字段使用同一 canonical 前缀规则；矛盾输入被拒绝 | UC-TYPED-REFS；CR-071 AC-3 |
| REQ-MF3-03 | 兼容 | v1 ref 兼容期采用 read-old/write-new：reader 必须确定读取或明确诊断，writer 只写 canonical v2，不得猜测 sibling/默认仓 | P1 | Given v1、ambiguous、unknown-role 和 writer fixtures，When 读写，Then 新 writer v1 输出=0、声明范围 v1 residual=0、ambiguous/misread 检出率=100%；连续两个 full-validation 快照 v1 input observed=0 前不得提议 reader 退役 | UC-TYPED-REFS；SGA-02；REV-03 |
| REQ-MF4-01 | 功能 | canonical successor 字段必须表达“默认执行策略/是否需要执行 full 层”，不得表达“禁止 full regression” | P0 | Given targeted→compatibility→full validation profile，When 读取 canonical 字段，Then full 层是否 required 可唯一判定且任何值都不构成运行禁令 | UC-FULL-REGRESSION-SEMANTICS；CR-071 AC-4 |
| REQ-MF4-02 | 兼容 | legacy `full_regression_allowed` reader 与迁移诊断必须保留到量化退役门槛达成并获后续批准，writer 只写 canonical successor | P0 | Given legacy/canonical fixture，When read-old/write-new，Then reader 输出 canonical policy 与 legacy provenance或明确迁移错误；writer v1 输出=0、声明范围 residual=0；reader 退役提议须连续两个 full-validation 快照 v1 input observed=0 | UC-FULL-REGRESSION-SEMANTICS；CR-071 AC-4；REV-03 |
| REQ-MF4-03 | 约束 | 字段迁移不得改变 targeted→compatibility→full 的固定验证顺序或跳过 required full 层 | P1 | Given profile 要求 full，When legacy/canonical 输入均被归一化，Then 执行计划仍含 targeted、compatibility、full 且顺序不变 | UC-FULL-REGRESSION-SEMANTICS；CR-071 AC-7 |
| REQ-MF5-01 | 功能 | 跨 Work receipt 复用必须用 canonical semantic-equivalence fixture matrix 比较 source、profile、command、environment、runner、evidence 和 provenance identity | P0 | Given 语义等价 runner/environment fixture，When 计算复用，Then 等价 fixture 误拒绝数=0；raw string 或 machine incidental differences 不得代替语义 identity | UC-VALIDATION-REUSE；CR-071 AC-5；REV-04 |
| REQ-MF5-02 | 约束 | 安全相关 identity 漂移、FAIL、命令漂移或 partial mutation receipt 不得复用，并只重跑失效层 | P0 | Given canonical 非等价安全漂移矩阵，When 计算复用计划，Then 安全相关漂移拒绝率=100%，stable 层保留、invalid 层重跑；FAIL/partial receipt 全部拒绝 | UC-VALIDATION-REUSE；CR-071 AC-5；REV-04 |
| REQ-MF5-03 | 非功能 | receipt 必须绑定可验证的 evidence/provenance 与 result digest，缺失或不可读时 fail closed | P1 | Given evidence path 缺失、provenance 不完整或 digest 不匹配，When 请求复用，Then 返回确定拒绝且不声明 cached PASS | UC-VALIDATION-REUSE；RISK-STALE-RECEIPT-REUSE |
| REQ-MF6-01 | 功能 | state/current projection 必须显式列出未登记失败、来源和 health/readiness 降级 | P0 | Given ledger 外失败或 baseline drift，When 生成 projection，Then state 与 current 均暴露 failure ID/source 并不再显示健康绿色 | UC-UNREGISTERED-FAILURE-VISIBILITY；CR-071 AC-6 |
| REQ-MF6-02 | 约束 | 缺少失败归属证据时 projection 必须 fail closed，不得把 unknown 静默归为 healthy | P0 | Given failure 存在但 owner/source 归属不足，When 投影，Then health 降级且 next action 指向补证/阻断，不伪造 owner 状态且不得手工修改 lifecycle/readiness/gate 等派生状态 | UC-UNREGISTERED-FAILURE-VISIBILITY；CR-071 AC-6；REV-05 |
| REQ-MF6-03 | 非功能 | 有效归属证据补齐后，一次成功 reprojection 必须退出阻断并使 state/current 收敛；稳定输入的再次投影保持语义 no-op | P1 | Given 因缺证阻断的 projection，When 补齐有效证据并执行一次 reprojection，Then blocked 状态退出且 state/current failure/health facts 一致；不得手工改派生状态，之后相同 source digest 的重投影语义 mutation=0 | UC-UNREGISTERED-FAILURE-VISIBILITY；SM-04；REV-05 |

## 变更记录

| 版本 | 操作 | 涉及需求 | 原因 / 来源 | 处理说明 |
|---|---|---|---|---|
| 1.0 | 初始化 | REQ-MF1-01～REQ-MF6-03 | CR-071 产品基线重整 | 新增 18 条需求；CP2 人工确认前保持 draft |
| 1.1 | 增量修订 | REQ-MF1-01～02、REQ-MF2-01/03、REQ-MF3-03、REQ-MF4-02、REQ-MF5-01～02、REQ-MF6-02～03 | formal CP2 changes_requested 六项 delta | 保留全部 18 个 ID；BL-001 归为 MF-2 前置，不新增 MF-7；formal CP2 仍 pending |

## 风险与假设

| ID | 类型 | 内容 | 关联需求 | 缓解措施 / 验证方式 |
|---|---|---|---|---|
| RA-001 | 风险 | scope-amend 若允许原地扩张会绕过 deny-default 审计 | REQ-MF2-01～03 | append-only revision、typed authorization、stale preimage/unknown path fixture |
| RA-002 | 风险 | 兼容读取若含隐式猜测会延续 ref/字段歧义 | REQ-MF3-03、REQ-MF4-02 | CP2 冻结兼容策略；ambiguous fixture 必须 fail closed |
| RA-003 | 风险 | receipt identity 不完整会复用陈旧 PASS | REQ-MF5-01～03 | 七类 identity 差异矩阵和缺证据 fixture |
| RA-004 | 风险 | 未登记失败可能被投影层遗漏或错误归属 | REQ-MF6-01～03 | unregistered/unknown-owner/baseline-drift fixture 与 state/current 一致性检查 |
| RA-005 | 假设 | canonical successor 字段的具体名称属于 CP3 schema 设计，不改变本文件冻结的产品语义 | REQ-MF4-01～03 | CP3 候选字段必须逐一通过“非禁令语义”场景模拟 |
| RA-006 | 风险 | preflight/apply 若各自维护校验规则会产生决策漂移 | REQ-MF1-01～02 | CP3 将 shared validation core/decision graph 设为 architecture invariant；fixture 对比 normalized decision |
| RA-007 | 风险 | 补证后若依赖手改派生状态，会掩盖 projection 未收敛 | REQ-MF6-02～03 | 两阶段 fixture：先 fail closed，补证后只允许一次 reprojection 收敛 |

## CP4 Mandatory Decomposition / Regression Inventory

> 此清单是后续 CP4 的强制分解与回归盘点入口，不声明这些文件已实现 MF-1～MF-6，也不声明当前已验证。

| Inventory ID | 类型 | 必须纳入 CP4 的对象 | 当前状态 |
|---|---|---|---|
| CP4-SRC-01 | source | `meta_flow/workflow/cr_cli.py` | mandatory-decomposition-pending |
| CP4-SRC-02 | source | `meta_flow/workflow/cr_index.py` | mandatory-decomposition-pending |
| CP4-SRC-03 | source | `meta_flow/work/model.py` | mandatory-decomposition-pending |
| CP4-SRC-04 | source | `meta_flow/state/formal_projection.py` | mandatory-decomposition-pending |
| CP4-TST-01 | test | `tests/test_cr_cli.py` | mandatory-regression-inventory-pending |
| CP4-TST-02 | test | `tests/test_cr_index.py` | mandatory-regression-inventory-pending |
| CP4-TST-03 | test | `tests/test_vnext_work_model_lifecycle.py` | mandatory-regression-inventory-pending |
| CP4-TST-04 | test | `tests/test_state_formal_projection.py` | mandatory-regression-inventory-pending |

## 里程碑建议

| 里程碑 | 包含需求 | 描述 |
|---|---|---|
| M1 - Work 生命周期安全 | REQ-MF1-01～REQ-MF2-03 | 先把晚发现和非法范围扩张变成 apply 前确定诊断 |
| M2 - 公共合同迁移 | REQ-MF3-01～REQ-MF4-03 | 冻结 typed ref 与 validation policy 的 canonical/legacy 语义 |
| M3 - 证据与投影可信 | REQ-MF5-01～REQ-MF6-03 | 安全复用稳定验证层并暴露未登记失败 |

## 默认假设（REQUIRED 级别澄清采用的默认值）

| ID | 假设内容 | 影响范围 |
|---|---|---|
| AS-001 | 基线按 CP2 review delta 采用 read-old/write-new 推荐合同和量化门槛；formal CP2 未批准前不得据此实施、退役 reader 或标记 approved | REQ-MF3-03、REQ-MF4-02 |
| AS-002 | 本地 fixture/dry-run 是 CP2 后验证设计的默认入口，不代表真实运行授权 | 全部需求 |

## 明确排除项（Out of Scope）

- quant-lab READ-PLAN、授权瘦身、Stage 3 绿色基线和项目侧 supersession 实践。
- quant-lab 仓库内任何数据、源码、测试或治理产物修改。
- commit/push/publish/release、网络、凭据、生产写、真实运行和真实安装。
- 本阶段的 HLD、Story 技术拆分、LLD 与实现。

## 目标平台

- [x] Codex（Meta Flow 当前 release/process 双仓）
- [ ] Claude Code（本轮产品基线不新增平台特有行为）
- [ ] OpenClaw（本轮产品基线不新增平台特有行为）

## 待人工决策

| Decision ID | 类型 | 状态 | 说明 |
|---|---|---|---|
| CP2-DQ-01 | scope | pending | 是否冻结 revision 2：MF-1～MF-6、BL-001 作为 MF-2 enabling prerequisite、CP3 shared-core invariant、CP4 四源码/四测试 mandatory inventory，且不新增 MF-7 |
| CP2-DQ-02 | implementation | pending-formal-freeze | formal CP2 是否冻结 review delta 指定的 read-old/write-new 及 SM-06 量化门槛；内容缺口已关闭但不等于已批准 |
