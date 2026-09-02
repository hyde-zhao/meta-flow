---
status: confirmed
version: "1.3"
confirmed: true
confirmed_by: "user"
confirmed_at: "2026-08-19T14:05:17Z"
ready_for_design: true
source_change: "CR-071 + CR-072 + CR-073"
source_use_cases:
  - UC-WORK-PREFLIGHT
  - UC-SCOPE-AMENDMENT
  - UC-TYPED-REFS
  - UC-FULL-REGRESSION-SEMANTICS
  - UC-VALIDATION-REUSE
  - UC-UNREGISTERED-FAILURE-VISIBILITY
  - UC-PLAN-COMPILER
  - UC-CLOSURE-BUILD
  - UC-PROCESS-COST
  - UC-SEMVER-DECISION
  - UC-RELEASE-ORDER
  - UC-PUBLISHED-ASSET-CONSUMER
  - UC-HISTORICAL-REFRAME
  - UC-WORK-INIT-PREFLIGHT
  - UC-WORK-SCOPE-AMEND
  - UC-FAILURE-RECOVERY
  - UC-VALIDATION-TRUTH
  - UC-VICTIM-REPLAY
total_requirements: 40
blocking_open_questions: 0
formal_cp2_status: approved
formal_cp2_approval_ref: "CR073-CP2-USER-DECISION-20260819-V1"
---

# CR-071 结构化需求

## 来源与治理上下文

| 字段 | 值 |
|---|---|
| 主输入 | `docs/product/USE-CASES.md` |
| 变更来源 | `process/changes/CR-071.md`、`process/works/CR-071-R2/REQUEST.md` |
| 目标产物类型 | `mixed`（tool/CLI、schema/typed contract、workflow/projection） |
| 治理方式 | `review-gated` / `strict` |
| 当前判定 | 内容缺口为 0；CR-072 CP2 已批准，`ready_for_design=true`；实现仍受 CP3/CP4/CP5 约束 |

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 | 文档处理方式 |
|---|---|---|---|---|
| 1.0 | 2026-08-15 | meta-pm | 为 MF-1～MF-6 建立 18 条初始需求 | 按 CR-071 决策新增，不覆盖历史对象 |
| 1.1 | 2026-08-15 | meta-pm | 在原 18 个 ID 上吸收 CP2 revision 2 六项 review delta | 增量修订；不新增 MF、REQ 或正式批准 |
| 1.2 | 2026-08-18 | meta-pm | 追加 CR-072 的 0.6.1 Package、closure、成本、SemVer、release-order 与消费者完整性需求 | 保留全部 CR-071 REQ；新增 REQ-072-01～12；CP2 已批准 |

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
| REQ-072-01 | 功能 | 系统必须将两个 planned Work 编译为单一 0.6.1 Package Plan，并裁决 package completeness、priority、ownership 和 public CLI registration | P0 | Given Work A/B 与候选 Package，When 编译 Plan，Then 输出唯一 canonical Plan IR；缺 package 字段、priority、owner 或 CLI 注册时 BLOCKED 且 mutation=0 | UC-PLAN-COMPILER；CR-072 |
| REQ-072-02 | 约束 | Package Plan 必须拒绝冲突 owner、重复/无效 priority 和未注册 public CLI，且不得以隐式默认值补齐 | P0 | Given 不完整或冲突输入，When 执行 compiler precheck，Then 返回逐项诊断、责任归属与恢复入口，不产生 Work/Story/状态写入 | UC-PLAN-COMPILER；RISK-PROCESS-BLOAT |
| REQ-072-03 | 功能 | closure-build 必须计算 direct 与 transitive affected closure，并将 SHA 作为 literal 输入处理 | P0 | Given changed root 与依赖图，When 计算 closure，Then 所有 direct/transitive dependent 被包含、SHA 不被归一化猜测，缺图或无效 SHA 时 BLOCKED | UC-CLOSURE-BUILD；CR-072 |
| REQ-072-04 | 非功能 | closure-build 只能计划 affected-only rebuild；稳定且不受影响的对象保持语义 no-op | P1 | Given 无影响输入或稳定 fingerprint，When 重新计算，Then build set 不扩大且除允许时间字段外 mutation=0 | UC-CLOSURE-BUILD；UC-PROCESS-COST |
| REQ-072-05 | 功能 | 系统必须从 append-only 记录和 receipt 派生 Package 自身过程成本，并先支持 measure-only baseline | P0 | Given 可验证的记录，When 生成 cost report，Then 输出来源、digest、qualification count 与 baseline comparison，不以人工汇总替代 | UC-PROCESS-COST；CR-072 |
| REQ-072-06 | 约束 | measure-only 转 hard-gate 后，超过批准阈值、unresolved CHECK_HARNESS_ERROR 或 qualification count>1 必须 fail closed | P0 | Given hard-gate 已启用且任一条件触发，When admission/qualification 评估，Then BLOCKED、列出受影响步骤与恢复条件 | UC-PROCESS-COST；UC-RELEASE-ORDER |
| REQ-072-07 | 功能 | SemVer classifier 必须先真实输出 minor/0.7.0 候选；不能将结构性改造伪装为 PATCH | P0 | Given 兼容性影响，When 分类，Then 输出可审计分类理由；breaking input 直接 BLOCKED | UC-SEMVER-DECISION；RISK-BREAKING-PATCH |
| REQ-072-08 | 兼容 | 仅允许 reusable=false 的 typed 0.6.1 bootstrap 覆盖非 breaking 的分类选择，且 token 不可复用 | P0 | Given non-breaking 分类与有效 token，When 请求 0.6.1，Then 只生成一次 0.6.1 decision；重复或跨版本使用 token 均 BLOCKED | UC-SEMVER-DECISION；CP2-DQ-02 |
| REQ-072-09 | 功能 | 发布状态机必须强制 source freeze → version decision → fingerprint → qualification → build → canary → tag/release 的顺序 | P0 | Given aggregate Package，When 任一步开始，Then 必须有前一步同源证据；倒序、跳步或 freeze drift 均 BLOCKED 并只失效受影响步骤 | UC-RELEASE-ORDER；CR-072 |
| REQ-072-10 | 约束 | 一个 Package 的 qualification、build、canary、CP8 与 release 各只允许最终一次；Work A/Work B 不得产生中间 release lineage | P0 | Given 任一 Work 单独完成或已有 qualification，When 请求中间动作/重复动作，Then 拒绝并保留唯一 aggregate lineage | UC-RELEASE-ORDER；RISK-QUALIFICATION-REPEAT |
| REQ-072-11 | 功能 | 最终 canary 必须在 clean-home 中仅消费 published asset，并验证 package completeness 与 public CLI 可用性 | P0 | Given 已构建资产和隔离 home，When 执行后续授权 canary，Then 不依赖源树；缺 asset/CLI 或 home 污染均确定失败 | UC-PUBLISHED-ASSET-CONSUMER；CR-072 |
| REQ-072-12 | 约束 | CR-072 不得通过新增 CR、Work、Story、CP 或中间 receipt 解决 checker/recovery；权限、安装、网络、发布均保持 deny-default | P1 | Given 任一恢复或检查修复提议，When 评估 scope，Then 超出 CR=1、Work=2、CP2=1 或非授权动作时返回新 revision/独立授权入口 | UC-PROCESS-COST；UC-RELEASE-ORDER |

## 变更记录

| 版本 | 操作 | 涉及需求 | 原因 / 来源 | 处理说明 |
|---|---|---|---|---|
| 1.0 | 初始化 | REQ-MF1-01～REQ-MF6-03 | CR-071 产品基线重整 | 新增 18 条需求；CP2 人工确认前保持 draft |
| 1.1 | 增量修订 | REQ-MF1-01～02、REQ-MF2-01/03、REQ-MF3-03、REQ-MF4-02、REQ-MF5-01～02、REQ-MF6-02～03 | formal CP2 changes_requested 六项 delta | 保留全部 18 个 ID；BL-001 归为 MF-2 前置，不新增 MF-7；formal CP2 仍 pending |
| 1.2 | 增量新增 | REQ-072-01～12 | CR-072 单一 0.6.1 Package 目标 | 不覆盖 CR-071；两 Work 仍 planned，未授权实施/资格化/发布 |

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
| RA-072-01 | 风险 | bootstrap 被复用或被误当 PATCH 会绕过兼容裁决 | REQ-072-07～08 | typed reusable=false token、breaking change BLOCKED、决策审计 |
| RA-072-02 | 风险 | freeze drift 或重复 qualification 产生双血缘/双成本 | REQ-072-09～10 | fingerprint 重验、qualification-once hard gate、affected-only recovery |
| RA-072-03 | 风险 | canary 从源树或污染 home 获得假阳性 | REQ-072-11 | clean-home、published-asset-only 与 CLI/package completeness fixture |
| RA-072-04 | 风险 | checker 恢复导致过程对象膨胀 | REQ-072-12 | CR=1/Work=2/CP2=1 预算，超出时新 revision/授权 |

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
| M4 - 0.6.1 单一 Package | REQ-072-01～12 | 编译两个 Work、保护 closure/成本/SemVer/release-order，并在一次血缘中验证已发布资产消费者 |

## 默认假设（REQUIRED 级别澄清采用的默认值）

| ID | 假设内容 | 影响范围 |
|---|---|---|
| AS-001 | 基线已按 CP2 review delta 冻结 read-old/write-new 合同和量化门槛；未达量化门槛且未经后续正式批准不得退役 reader | REQ-MF3-03、REQ-MF4-02 |
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

## 人工决策记录

| Decision ID | 类型 | 状态 | 说明 |
|---|---|---|---|
| CP2-DQ-01 | scope | approved-2026-08-16 | 冻结 revision 2：MF-1～MF-6、BL-001 作为 MF-2 enabling prerequisite、CP3 shared-core invariant、CP4 四源码/四测试 mandatory inventory，且不新增 MF-7 |
| CP2-DQ-02 | implementation | approved-2026-08-16 | formal CP2 冻结 review delta 指定的 read-old/write-new 及 SM-06 量化门槛 |
| CP2-DQ-01-072 | scope | approved-2026-08-18 | 冻结单一 0.6.1 Package、两个 planned Work 和一次最终 release lineage，不产生中间版本/资格化/发布 |
| CP2-DQ-02-072 | compatibility | approved-2026-08-18 | 冻结不可复用的 typed 0.6.1 bootstrap；breaking change 仍必须 BLOCKED |
| CP2-DQ-03-072 | admission | approved-2026-08-18 | 接受 P5-0.6.1-release-convergence admission 建议，后续由长期治理 owner 更新 Roadmap/Phase |
| CP2-DQ-04-072 | sequencing | approved-2026-08-18 | 接受先 measure-only，再在 Work A 后实施 Work B 主体并最终一次 qualification/release 的顺序 |
| CP2-DQ-073-01 | scope | approved-2026-08-19 | 冻结 C0.5、一个 CR/两个 Work/七能力槽、六轮到三旅程矩阵及受害者验收边界 |
| CP2-DQ-073-02 | runtime_authorization | approved-2026-08-19 | 只冻结外部回放授权硬门，不授予 quant-lab、安装、发布或 Git 权限 |

## CR-073 增量需求（CP2 已确认）

| ID | 优先级 | 验收条件（Given/When/Then） | 来源 |
|---|---|---|---|
| REQ-073-01 | P0 | Given 历史证据不足 When historical-reframe Then 只追加 audit binding/`audited-known-historical-fact`，不伪造 CP6/CP7 PASS | UC-HISTORICAL-REFRAME |
| REQ-073-02 | P0 | Given Work init When preflight Then success/failure lifecycle、index、tuple、manifest、typed refs 在 mutation=0 前诊断 | UC-WORK-INIT-PREFLIGHT |
| REQ-073-03 | P0 | Given paused/blocked G1 Work When additive amend Then 只增 scope、重新授权并失效受影响 evidence | UC-WORK-SCOPE-AMEND |
| REQ-073-04 | P0 | Given FAIL receipt/observation 缺失 When projection Then warning/block，不能 continue_active_work 假健康 | UC-FAILURE-RECOVERY |
| REQ-073-05 | P0 | Given reuse candidate When identity 任一漂移 Then RUN 受影响层；仅完整 PASS identity 可复用 | UC-VALIDATION-TRUTH |
| REQ-073-06 | P0 | Given 六轮事故 When 验收 Then 每轮映射 J1/J2/J3 且 R3 人工项有归属 | UC-VICTIM-REPLAY |
| REQ-073-07 | P0 | Given 无独立 typed external authorization When source-candidate replay Then 不读/不执行/不写外部项目并保留 BLOCKED | UC-VICTIM-REPLAY |
| REQ-073-08 | P1 | Given 下一发布 When consumer acceptance Then installed-artifact replay 是硬门；本 CR 不自动获得安装/发布授权 | UC-VICTIM-REPLAY |
| REQ-073-09 | P1 | Given 进入设计 When 计数 Then 预算为 1 CR/2 Work/7 capability slots，CP2 前不拆过程 Story | CR-073 budget |
| REQ-073-10 | P1 | Given P7 缺口 When 建立 P6 基线 Then STATE-CONTRACT、pause/resume、cost hard-gate 只作 P7 handoff | P7 plan |

## CR-075 增量需求（P6 Stage 3；2026-08-24 CP7 门禁反馈第 8 项授权补录，CP2 回溯确认随 CP7 approve 一并生效）

| ID | 优先级 | 验收条件（Given/When/Then） | 来源 |
|---|---|---|---|
| REQ-075-P0 | P0 | Given 0.6.3 provider 基线 When transaction primitive 收敛 Then facade 唯一实现、跨 owner 私有导入清零、兼容 alias 保留一个版本周期、行数不超 HLD §2.1-rev3 警戒线 | CR-075 P0 |
| REQ-075-S01 | P0 | Given Work init/alteration When preflight Then lifecycle/registry/tuple/manifest/typed-ref 诊断在 mutation=0 前完成且 journey 映射 J1 | CR-075 Work A |
| REQ-075-S02 | P0 | Given paused/blocked G1 Work When handoff-free scope amend Then 只增 scope、重新授权、失效联动最小集 | CR-075 Work A |
| REQ-075-S03 | P0 | Given 依赖 DAG When dependency supersession Then 闭环登记且环/悬空阻断 fail closed | CR-075 Work A |
| REQ-075-S04 | P0 | Given ValidationPolicyV2 When CLI 执行 Then 分层验证 receipt 绑定 source/profile fingerprint、命令身份、环境摘要与 result digest；fingerprint 漂移不复用 | CR-075 Work B |
| REQ-075-S05 | P0 | Given Work close When usage terminal 非法（hard stop/超限未处理/usage_ref 缺失）Then BLOCK_CLOSE fail closed；合法 legacy 形态只 deprecate 不阻断 | CR-075 Work B |
| REQ-075-S06 | P0 | Given Phase 绿集 When baseline lifecycle Then typed plan/apply、append-only 修订历史、五类归属矩阵（绿转红无漂移=NEW_REGRESSION；基线外=UNATTRIBUTABLE） | CR-075 Work B |
| REQ-075-AGGREGATE | P0 | Given 七 Story 交付 When 兼容集回归 Then targeted→compatibility→full 分层全绿（存量窗口外失败单列），CR-075 变更窗口内零回归 | CR-075 CP7 |

## CR-076 增量需求（P6 收口：Distribution, Publication & P6 Closure；2026-08-27 CP2-CR-076 revision 3 落轴，确认随 CP2 approve 生效）

| ID | 优先级 | 验收条件（Given/When/Then） | 来源 |
|---|---|---|---|
| REQ-076-S01 | P0 | Given release chain 风险原因 When 分类 Then RiskReasonPolicyV1 输出 G0/G1/G2/unknown；ordinary 不自动升级 G2；public/security/production 变更 fail closed；G0/G1 N/A CP8 不等于 N/A authorization | CR-076 Work A S01 |
| REQ-076-S02 | P0 | Given 链上操作 When 授权输入 Then --authorization-file/ref/id 恰一解析、前驱 receipt 校验、operation registry 匹配；exactly-one/none/多选/错误 namespace/过期/复用/OID 漂移全部负向阻断 | CR-076 Work A S02 |
| REQ-076-S03 | P0 | Given 发布候选 When 资产构建 Then wheel/sdist/receipt/sidecar 单次 content-addressed 构建且各自 SHA-256 可追溯；source→accepted→published→installed 四重 identity 一致；缺失/重复/错版本/损坏/mismatch fail closed | CR-076 Work B S03 |
| REQ-076-S04 | P0 | Given consumer 环境 When 安装/升级/回滚 Then clean-home 安装、升级、降级、回滚、重复安装幂等、部分失败恢复全部有界；user/project scope、权限不足、symlink/outside path、缓存污染 fail closed | CR-076 Work B S04 |
| REQ-076-S05 | P0 | Given consumer 独立 replay When 回传结果 Then ConsumerAcceptanceResultV1 三字段组（authorization/artifact/execution identity）schema+digest 校验通过方可导入；漂移即失效；无 canonical result/源码 PASS/fixture PASS/provider canary 不可替代，只能 BLOCKED | CR-076 Work B S05 |
| REQ-076-AGGREGATE | P0 | Given CR-076 交付与两个 replay 硬门（source-candidate、installed-artifact）When P6 收口 Then CP8 后独立 publication authorization 且远端 asset digest == consumer 已验收 digest；active CR/Work 归零、stale refs 归零、follow-up owner 交接 P7/P8/P9、native phase transition | CR-076 CP8/P6 close |
