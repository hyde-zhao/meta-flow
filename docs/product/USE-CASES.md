---
status: confirmed
version: "1.3"
confirmed_by: "user"
confirmed_at: "2026-08-19T14:05:17Z"
engagement_mode: meta-self-dev
scenario_subject_type: implementation-carrier
scenario_subject_id: "meta-flow"
target_artifact_type: mixed
governance_mode: review-gated
review_policy: strict
delivery_routing:
  mode: meta-flow-delivery
  output_root: "meta-flow/"
  source: meta-self-dev
total_use_cases: 18
formal_cp2_status: approved
formal_cp2_approval_ref: "CR073-CP2-USER-DECISION-20260819-V1"
---

# CR-071 使用场景基线

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 | 文档处理方式 |
|---|---|---|---|---|
| 1.0 | 2026-08-15 | meta-pm | 为 MF-1～MF-6 建立初始场景基线 | 按 CR-071 文档处理决策新增；正式 CP2 确认待定 |
| 1.1 | 2026-08-15 | meta-pm | 吸收 CP2 changes_requested 六项增量 | 保留 6 个 UC；formal CP2 仍 pending |
| 1.2 | 2026-08-18 | meta-pm | 增量建立 CR-072 单一 0.6.1 Release Package 场景族 | 保留 CR-071 全部 UC/映射；新增 UC-PLAN-COMPILER～UC-PUBLISHED-ASSET-CONSUMER；CP2 已批准 |
| 1.3 | 2026-08-19 | meta-pm | 增量建立 CR-073 admission-safety 场景族 | 保留 CR-071/072 历史；新增 6 UC；CP2 已批准 |

## 用户画像（Personas）

| 画像 ID | 角色名称 | 典型背景 | 核心诉求 | 技术水平 |
|---|---|---|---|---|
| P-01 | Meta Flow 工作流维护者 | 负责创建、修订和排查结构化 Work | 在 apply 前发现机械错误，安全修订范围并减少返工 | 高级 |
| P-02 | Host Orchestrator | 负责阶段路由、授权边界和检查点推进 | 获得一致的引用、验证与状态事实，避免误推进 | 高级 |
| P-03 | 质量审查与审计人员 | 复核验证证据、迁移兼容和失败可见性 | 确认证据可复用但不陈旧，失败不会被投影成健康 | 高级 |

## 成功指标（Success Metrics）

| 指标 ID | 指标名称 | 度量方式 | 目标值 |
|---|---|---|---|
| SM-01 | apply 前错误拦截与决策同源率 | 对无效 ref、revision、scope、budget、on-touch fixture 分别调用 preflight/apply 的共享 validation core | 100% 在 mutation 前报告且 preflight mutation=0；同一快照的 normalized decision graph 100% 一致 |
| SM-02 | 范围修订审计完整率 | 检查 revision>1 legal supersession admission、scope-amend revision、重新分类、重新授权和证据失效记录 | 100%；未通过 predecessor/inventory admission 时 MF-2 不得进入实现或 E2E 验收 |
| SM-03 | receipt 语义等价与安全漂移判定率 | 用 canonical semantic-equivalence fixture matrix 比较 runner/environment 等价与安全相关漂移 | 等价 fixture 误拒绝数=0；非等价且安全相关的漂移拒绝率=100% |
| SM-04 | 未登记失败可见与恢复率 | 注入缺失归属证据，补齐证据后执行一次 reprojection 并读取 state/current | 缺证时 100% fail closed；补证后一次 reprojection 100% 退出阻断并收敛，手工派生状态修改=0 |
| SM-05 | 产品追溯完整率 | 核对 MF → UC → REQ → SCN → Story 映射 | MF-1～MF-6 全部 100% 覆盖 |
| SM-06 | v1 writer/reader 退役就绪度 | 检查新 writer 输出、声明范围残留、歧义识别与连续 full-validation 快照中的 v1 输入观测 | 新 writer v1 输出=0；声明范围 v1 residual=0；ambiguous/misread 检出率=100%；连续两个 full-validation 快照 v1 input observed=0 后才可提议 reader 退役 |

## 明确排除（Out of Scope）

- quant-lab READ-PLAN 检查单、授权文本瘦身、Stage 3 绿色基线和项目侧 supersession 实践。
- 在 quant-lab 产品仓复制 Meta Flow 内部校验语义或创建第二套治理真相。
- git commit、push、merge、tag、publish、release。
- 网络、凭据、外部项目、生产写、真实运行和真实安装。
- CP2 前的 HLD、Story 技术拆分、LLD 或代码实现。

## 治理附录（Governance）

| 字段 | 当前值 | 说明 |
|---|---|---|
| `engagement_mode` | `meta-self-dev` | 用户明确要求继续补齐 Meta Flow 本体能力 |
| `scenario_subject_type` | `implementation-carrier` | 当前仓库既是场景主体也是后续实现载体 |
| `scenario_subject_id` | `meta-flow` | 本基线只服务 Meta Flow MF-1～MF-6 |
| `target_artifact_type` | `mixed` | 同时涉及 CLI/tool、schema/typed contract 和 workflow/projection，触发方式与落盘面不同 |
| `governance_mode` | `review-gated` | 公共合同、授权和验证证据均受正式门禁约束 |
| `review_policy` | `strict` | CR 类型为 architecture-major，CP2/CP3/CP5/CP8 均需人工门 |
| `delivery_routing.mode` | `meta-flow-delivery` | 本轮是 meta-self-dev |
| `delivery_routing.output_root` | `meta-flow/` | 产品、源码、测试和交付文档均留在 Meta Flow release repo |
| `delivery_routing.source` | `meta-self-dev` | 来源为用户明确边界修正和 CR-071 |

`mixed` 拆分理由：MF-1/MF-2 是 Work 操作入口，MF-3/MF-4/MF-5 是公共 schema/验证合同，MF-6 是状态投影行为；三类对象需要不同的实现与验证链路，但共享同一安全边界和 CP2 产品基线。

## 头脑风暴与候选方案

| 候选 ID | 候选理解 / 交付形态 / 输出路径 | 对范围的影响 | 对复杂度的影响 | 对验证的影响 | 交付出口影响 | 是否主选 |
|---|---|---|---|---|---|---|
| OPT-01 | 仅补齐 Meta Flow MF-1～MF-6 | 固定六项公共能力 | 中等，可按三组切片 | 需要 contract、migration、projection 和分层回归 | 仅 Meta Flow 双仓 | 是 |
| OPT-02 | 同时纳入外部目标项目止血制度 | 扩大到项目侧流程与数据 | 高，产生双重真相风险 | 需外部仓真实基线和独立授权 | 跨项目 | 否 |
| OPT-03 | 只做 MF-1/MF-2 的紧急子集 | 缩小到 Work 生命周期 | 低，但保留合同误读与陈旧证据问题 | 只能证明局部改善 | 仅 Meta Flow 双仓 | 否 |

**分段确认记录**：

| 确认项 | 结论 | 确认来源 |
|---|---|---|
| 场景主体 | 已回答并经 CP2 正式确认 | 用户最新 freeform；`process/works/CR-071-R2/REQUEST.md` |
| 交付出口 | 已回答并经 CP2 正式确认 | Meta Flow 本体边界；CR-071 文档处理决策 |
| 主选方案 | OPT-01 | 用户要求“继续完成 meta-flow 侧的改进点进行能力补齐” |

## Scenario Gray Areas

**讨论日志**：`process/discussions/CP2-CR071-DISCUSSION-LOG.md`

**恢复点**：`process/checks/CP2-CR071-DISCUSSION-CHECKPOINT.json`

| 灰区 ID | 问题 | 为什么重要 | 影响面 | 推荐讨论顺序 | 状态 | canonical refs |
|---|---|---|---|---:|---|---|
| SGA-01 | 本轮主体是 Meta Flow 六项能力，还是同时扩大到外部目标项目制度？ | 决定仓库边界、授权和真相源数量 | 范围、复杂度、验证、交付出口 | 1 | resolved-by-freeform | REQUEST、CR-071、SGQ-001 |
| SGA-02 | legacy 兼容期采用 read-old/write-new、双写还是硬切换？ | 决定迁移风险、诊断和退役成本 | 范围、验证、维护、后续门控 | 2 | quantified-recommendation-approved | CR-071 验收标准 3/4、CP2-DQ-02、SM-06 |
| SGA-03 | init-preflight 是局部语法检查还是全生命周期零写模拟？ | 决定能否提前发现 scope、revision、budget 与 on-touch 错误 | 用户价值、复杂度、验证 | 3 | resolved-with-shared-core-invariant | CR-071 验收标准 1、CP2 revision 2 |
| SGA-04 | receipt 漂移后全量重跑还是只重跑失效层？ | 决定验证成本与错误复用风险 | 性能、证据、验证、维护 | 4 | resolved-with-semantic-equivalence-thresholds | CR-071 验收标准 5、SM-03 |

**用户选择记录**：

| 时间 | 用户选择 | 处理方式 | 确认记录 |
|---|---|---|---|
| 2026-08-15 | 选择 SGA-01 的 Meta Flow 本体边界；接受 SGA-03/04 的 CR 合同方向 | 记录 freeform 回答并复述理解；正式门保持 pending | SGQ-001=`answered`，不得提前写为 `confirmed` |

## 用户可见场景确认证据

| Question ID | 问题 | 选项 / 候选理解 | 推荐方案 | 用户回答 | 复述确认 | 影响面 | 来源 | 状态 |
|---|---|---|---|---|---|---|---|---|
| SGQ-001 | 本轮应只补齐 Meta Flow MF-1～MF-6，还是把外部项目侧止血对象一并纳入？ | A. 仅 MF-1～MF-6；B. 同时纳入外部项目；C. 仅先做 MF-1/MF-2 | A，仅 MF-1～MF-6 | “继续完成 meta-flow 侧的改进点进行能力补齐” | 已理解为：当前产品基线固定为 MF-1～MF-6；外部项目对象不进入本仓实现；该理解已回答但仅由 host 的 CP2 approve 才能正式确认 | scope、validation、delivery、gate | 用户 freeform、REQUEST、CR-071 | answered |

## MF-2 Enabling Prerequisite

| ID | 归属 | 当前状态 | 硬门槛 | 非目标 |
|---|---|---|---|---|
| BL-001 | MF-2 enabling prerequisite | current-scope-required | revision>1 的 legal supersession admission 必须在 MF-2 实现和端到端验收前证明 predecessor/inventory 可被确定接纳；失败时 MF-2 fail closed | 不新增 MF-7；不在 CP2 实现 bootstrap 修复 |

## Deferred Ideas

| ID | 想法 / 风险 / 扩展场景 | 来源 | 延后原因 | 触发重启条件 |
|---|---|---|---|---|
| DEF-02 | legacy reader 的实际退役日期 | SGA-02 | 当前基线已量化退役就绪门槛，但实际日期需要迁移期观测 | SM-06 全部达标并经后续正式决策批准 |
| DEF-072-01 | 将 0.6.1 bootstrap 机制复用到后续版本 | CR-072 SemVer 边界 | 一次性 bootstrap 只能为 0.6.1 保留，不得成为一般跳过分类器 | 新 CR 且独立 SemVer/兼容评审通过 |

## 使用场景列表

### UC-GOVERNANCE-PROFILE-SELECTION：治理风险档的选择、归一与升级失效

| 字段 | 内容 |
|---|---|
| **使用角色** | P-01、P-02 |
| **触发条件** | 发起人或 Host 对一个候选变更做 Work/CR 治理风险档分类，或用户在分类结果上表达设计保障偏好 |
| **输入** | RiskFacts（变更种类/路径数/可逆性/多模块/多步等）、用户表述（如「做完整 LLD」「按原 G2 完整流程」「每 Story 详细设计」「G3」）、既有 CR/Work 持久 profile（含 schema version） |
| **处理逻辑** | Given 变更事实与用户表述，When 执行 classify，Then：G0/G1 判定与预算不变；高风险事实命中默认落 V2 G2（scope-goal-note 保障路径）；用户明确要求完整 LLD/原 G2 完整流程/G3 时由 Host 归一为 typed `requested_profile=G3 + selection_source=user-explicit + authorization_ref`（Agent/config 不得伪造 user-explicit）；G2 运行中命中 credential/security/production-write/不可逆迁移/公共 schema/事务并发等触发且 scope-goal-note 不足时返回 `G3_CONSENT_REQUIRED` 并 BLOCKED，仅用户明确批准后升级；迟到升级按冻结的 invalidation 规则失效旧证据；G3→G2 一律拒绝 |
| **输出/结果** | 四级分类决策 + 原因码；typed selection record；consent-required 阻断或升级生效；历史 V1 G2 对象保持 legacy 完整保障语义、bytes 零改写 |
| **前置条件** | profile schema version 合同已冻结；分类器与门配置可用 |
| **排除情况** | 不适用于 CR-076 publication operation 的 `RiskGrade.G0/G1/G2`（operation 级三档，独立命名空间）；不做 Story 级混合 profile |

**处理流程（文字描述）：**
1. 采集事实并运行 classify（默认路由）。
2. 识别用户显式设计保障要求并归一为 typed selection。
3. 命中 consent-required 触发时阻断并等待用户批准。
4. 记录 selection/升级来源与失效边界，绑定 route plan 与后续证据链。

### UC-WORK-PREFLIGHT：在 apply 前模拟完整 Work 生命周期

| 字段 | 内容 |
|---|---|
| **使用角色** | P-01、P-02 |
| **触发条件** | 维护者准备初始化或重建结构化 Work，但尚未授权 apply |
| **输入** | 目标 root/slice/revision、typed refs、scope、budget、risk/profile 和 on-touch obligations |
| **处理逻辑** | Given 输入快照与当前 OID/preimage 可读，When 执行 `work init-preflight`，Then 通过与 apply 共用的单一 validation core/decision graph 模拟成功与失败全生命周期 I/O，并校验 ref、revision、scope closure、budget 和 on-touch obligations，全程保持 mutation=0；两入口只允许 orchestration/presentation 不同 |
| **输出/结果** | 可机读的 PASS/BLOCKED 诊断、逐项失败原因、计划写集合和 mutation=0 证明 |
| **前置条件** | release/process route 健康；目标存在性和授权边界已知；无真实 apply 授权也可执行只读预检 |
| **排除情况** | 不创建 Work、不修改 ledger/state/current、不隐式申请新授权 |

**处理流程（文字描述）：**
1. 捕获输入快照与目标 preimage。
2. 模拟全部 lifecycle 写点和验证义务。
3. 返回确定性诊断与零写证明，失败时停在 apply 之前。

---

### UC-SCOPE-AMENDMENT：以新 revision 受控扩大 Work 范围

| 字段 | 内容 |
|---|---|
| **使用角色** | P-01、P-02、P-03 |
| **触发条件** | 活跃 Work 发现合法新增读写或检查需求，原 scope 不足 |
| **输入** | 当前 Work revision/preimage、追加 scope delta、变更理由、typed authorization 与受影响证据集合 |
| **处理逻辑** | Given 当前 revision 和授权有效，When 执行 scope-amend，Then 创建 append-only 新 revision，重新分类、重新授权并失效受影响 receipt/gate evidence；任何前置不满足时零写拒绝 |
| **输出/结果** | 新 revision、scope delta、授权/分类结果、失效清单与下一允许阶段 |
| **前置条件** | BL-001 revision>1 legal supersession admission 已通过；目标 Work active；OID/preimage 一致；delta 未越过 deny-default 边界 |
| **排除情况** | 不原地修改旧 revision，不把 `approve` 当运行授权，不保留受影响旧证据为可复用 |

**处理流程（文字描述）：**
1. 验证 revision、scope delta 与授权。
2. 生成 append-only revision 并计算证据失效面。
3. 原子提交或零写失败，保留完整审计链。

---

### UC-TYPED-REFS：用仓库角色消除引用前缀歧义

| 字段 | 内容 |
|---|---|
| **使用角色** | P-01、P-02、P-03 |
| **触发条件** | Work、receipt、context 或 projection 需要引用 release/process 仓对象 |
| **输入** | 带 repository role、logical namespace 和 object kind 的 typed ref，或迁移期 v1 ref |
| **处理逻辑** | Given ref 输入，When 解析/校验，Then 先按仓库角色和统一前缀语义解析；兼容期采用 read-old/write-new：可确定读取 v1、只写 canonical v2，并保留 provenance/诊断；新 writer 的 v1 输出和声明范围 residual 必须均为 0，ambiguous/misread 检出率必须为 100% |
| **输出/结果** | canonical typed ref、解析角色/路径语义、兼容或迁移诊断 |
| **前置条件** | 项目 route identity 健康；typed ref schema/version 可识别 |
| **排除情况** | 不猜 sibling、不去掉 `process/` 前缀、不把未知角色降级为默认仓；未连续两个 full-validation 快照观测到 v1 input=0 前不得提议退役 reader |

**处理流程（文字描述）：**
1. 校验 schema/version 与 repository role。
2. 统一解析相邻字段的前缀语义。
3. 输出 canonical ref 或确定的迁移诊断。

---

### UC-FULL-REGRESSION-SEMANTICS：明确全量回归字段表示执行策略

| 字段 | 内容 |
|---|---|
| **使用角色** | P-01、P-02、P-03 |
| **触发条件** | 创建或读取 validation profile/receipt，决定 targeted→compatibility→full 的执行要求 |
| **输入** | 新 canonical 执行策略字段，或迁移期 `full_regression_allowed` v1 字段 |
| **处理逻辑** | Given validation profile，When 读取策略，Then canonical 语义只描述默认执行策略与是否需要执行 full 层，不表达“禁止全量回归”；read-old/write-new 兼容 reader 对 v1 输入产生确定读取或明确迁移诊断，新 writer 不再输出 v1 |
| **输出/结果** | 无禁令歧义的 canonical 策略、迁移诊断和分层验证决策 |
| **前置条件** | CP2 冻结产品语义；CP3 决定具体字段命名/版本化方案 |
| **排除情况** | 不借字段值跳过 required full 层，不把未授权运行写成已执行 |

**处理流程（文字描述）：**
1. 识别 schema/version 和 legacy 字段。
2. 归一化为默认执行策略语义。
3. 按 targeted→compatibility→full 路由并保留迁移证据。

---

### UC-VALIDATION-REUSE：只复用身份完全一致的验证 receipt

| 字段 | 内容 |
|---|---|
| **使用角色** | P-02、P-03 |
| **触发条件** | 新 Work/新 revision 希望复用既有验证层结果 |
| **输入** | receipt 与当前 source/profile/command/environment/runner/evidence/provenance identity |
| **处理逻辑** | Given 候选 receipt，When 请求复用，Then 按 canonical semantic-equivalence fixture matrix 比对全部身份；语义等价才复用，任一安全相关漂移拒绝受影响层并只重跑失效层，失败或 partial mutation receipt 不可复用；raw string 或 machine incidental differences 不得代替语义 identity |
| **输出/结果** | reuse/reject 结论、差异维度、失效层和重跑计划 |
| **前置条件** | receipt 可验证、证据路径存在、provenance 完整 |
| **排除情况** | 不跨身份复用，不用旧 PASS 掩盖 FAIL，不无条件全量重跑 |

**处理流程（文字描述）：**
1. 校验 receipt 与证据存在性。
2. 比对七类身份并计算受影响层。
3. 复用稳定层，只重跑失效层并生成新 receipt。

---

### UC-UNREGISTERED-FAILURE-VISIBILITY：在 state/current 中显式暴露未登记失败

| 字段 | 内容 |
|---|---|
| **使用角色** | P-02、P-03 |
| **触发条件** | 投影 state/current 时发现 ledger 外失败、基线漂移或缺少归属证据 |
| **输入** | formal truth、ledger、失败源、baseline/preimage 和 projection inputs |
| **处理逻辑** | Given projection inputs，When 存在未登记失败或漂移，Then 显式列出失败、来源和归属状态，降低 health/readiness；缺少归属证据时 fail closed；补齐有效证据后一次成功 reprojection 必须退出阻断并使 state/current 收敛，全程不得手工修改派生状态 |
| **输出/结果** | 含 unregistered failures、source refs、health degradation 和 next action 的一致 state/current projection |
| **前置条件** | formal truth 与当前 projection inputs 可读；投影 writer 不手工覆盖 owner 状态 |
| **排除情况** | 不静默丢弃 ledger 外失败，不把 unknown 归为 healthy，不手工改派生 lifecycle/gate 状态 |

**处理流程（文字描述）：**
1. 比对 formal truth、ledger 与 projection inputs。
2. 分类未登记失败、漂移和未知归属。
3. 同步 state/current 的降级事实或 fail-closed 结论。

---

## CR-072 / 0.6.1 Release Package 增量场景

> 本节是增量基线：CR-071 的 UC 与指标保持可追溯，CR-072 增量已由 CP2 确认。Work A（稳定化/消费者完整性）与 Work B（治理编译器/成本/发布机器门）是同一 0.6.1 价值包的实施单元；不得形成中间版本、资格化或发布。

### UC-PLAN-COMPILER：把候选 Work 归一为可裁决的 Package

| 字段 | 内容 |
|---|---|
| **使用角色** | P-01、P-02、P-03 |
| **触发条件** | 编排者准备将 Work A、Work B 纳入唯一 0.6.1 Package |
| **输入** | Work 候选、Plan IR、依赖、priority、ownership、public CLI 注册和 package manifest |
| **处理逻辑** | 编译器只接受完整、可归属、可排序且 public CLI 已注册的候选；缺字段、重复 owner、无效 priority 或未注册 public CLI 均 fail closed |
| **输出/结果** | canonical Package plan、completeness/ownership/priority 诊断与零写拒绝结果 |
| **前置条件** | 两 Work 仅为 planned；无 CP2 之后的 Story 或实现对象 |
| **排除情况** | 不创建 Work/Story、不执行 package apply |

### UC-CLOSURE-BUILD：按受影响 closure 构建唯一包

| 字段 | 内容 |
|---|---|
| **使用角色** | P-01、P-03 |
| **触发条件** | 一个候选对象或依赖 SHA 发生变化，需要计算构建影响面 |
| **输入** | direct/transitive dependency graph、literal SHA、changed roots、package manifest |
| **处理逻辑** | 直接和传递依赖均进入 closure；SHA 必须按 literal 解释；只重建 affected closure，未受影响对象不被伪造为需要重建 |
| **输出/结果** | 可复核 closure、affected-only build plan，或 deterministic BLOCKED |
| **前置条件** | graph 与 package identity 可解析 |
| **排除情况** | 不执行真实 build，不以全量重建掩盖 closure 缺陷 |

### UC-PROCESS-COST：由 measure-only 过渡到可审计硬门

| 字段 | 内容 |
|---|---|
| **使用角色** | P-02、P-03 |
| **触发条件** | Package 需要报告自身过程成本或评价资格化次数 |
| **输入** | append-only 成本记录、zero-write receipt、baseline、hard-gate policy |
| **处理逻辑** | 初期只测量并保留 baseline；启用 hard gate 后超过阈值、未关闭 harness error 或重复 qualification 必须阻断；相同输入重算为语义 no-op |
| **输出/结果** | machine-derived 指标、门控决策与恢复指引 |
| **前置条件** | 指标来源和阈值版本可追溯 |
| **排除情况** | 不靠人工汇总或隐含时间戳证明成本合规 |

### UC-SEMVER-DECISION：真实分类后仅一次 bootstrap 选择 0.6.1

| 字段 | 内容 |
|---|---|
| **使用角色** | P-02、P-03 |
| **触发条件** | source freeze 前需要决定唯一版本 |
| **输入** | 兼容性影响、SemVer classifier 结论、typed bootstrap token、目标版本 |
| **处理逻辑** | classifier 必须真实推荐 minor/0.7.0；仅 non-breaking 情况可由不可复用的 typed bootstrap 选择 0.6.1；breaking change 始终 BLOCKED |
| **输出/结果** | 分类证据、一次性版本决策或 BLOCKED |
| **前置条件** | 兼容性输入和 bootstrap 身份可验证 |
| **排除情况** | 不伪造 PATCH，不把 bootstrap 复用于后续版本 |

### UC-RELEASE-ORDER：以一次 release lineage 完成最终交付

| 字段 | 内容 |
|---|---|
| **使用角色** | P-01、P-02、P-03 |
| **触发条件** | Work A/B 均满足候选完成条件并准备聚合发布 |
| **输入** | source fingerprint、version decision、qualification receipt、build/canary evidence、release state |
| **处理逻辑** | 固定顺序为 source freeze → version decision → fingerprint → qualification → build → clean-home canary → tag/release；freeze drift、重复 qualification 或顺序倒置均阻断并只回到受影响步骤 |
| **输出/结果** | 一个 aggregate lineage 或可解释的恢复 plan |
| **前置条件** | 两 Work 均在同一 Package 内；CP8 与发布授权另行取得 |
| **排除情况** | Work A 完成后不得单独 release/receipt/sidecar |

### UC-PUBLISHED-ASSET-CONSUMER：以干净 home 验证已发布资产消费者完整性

| 字段 | 内容 |
|---|---|
| **使用角色** | P-01、P-03 |
| **触发条件** | 最终 build 后需要验证发布资产，而非源树偶然可用性 |
| **输入** | 已构建资产、isolated clean-home、公开 CLI 入口、canary contract |
| **处理逻辑** | canary 仅消费已发布资产；缺失 package 文件、未注册 CLI、home 污染或真实安装授权不足均明确失败；通过后仍不等于 release 已执行 |
| **输出/结果** | planned canary evidence contract 或 fail-closed 诊断 |
| **前置条件** | 后续获得独立安装/运行授权；本阶段只定义验证场景 |
| **排除情况** | 不读取凭据、不做真实安装、不触碰外部项目 |

<!-- coverage-checklist: begin -->
## 附录：覆盖自检表

| 维度 ID | 维度名称 | 状态 | 涉及场景 | 备注 |
|---|---|---|---|---|
| D1 | 用户维度 | 已覆盖 | 全部 UC | 覆盖维护者、编排者和审查者 |
| D2 | 任务维度 | 已覆盖 | 全部 UC | 覆盖初始化、修订、迁移、复用、投影与故障处理 |
| D3 | 动机维度 | 已覆盖 | 全部 UC | 成功指标聚焦晚失败、重复验证和失败遗漏成本 |
| D4 | 时间维度 | 已补充 | UC-WORK-PREFLIGHT、UC-SCOPE-AMENDMENT、UC-TYPED-REFS、UC-FULL-REGRESSION-SEMANTICS | 区分首次、变更、迁移期和退役条件 |
| D5 | 环境维度 | 已覆盖 | UC-VALIDATION-REUSE、UC-UNREGISTERED-FAILURE-VISIBILITY | runner/environment 漂移和多仓 route 均进入验证 |
| D6 | 方式维度 | 已覆盖 | UC-WORK-PREFLIGHT、UC-SCOPE-AMENDMENT、UC-TYPED-REFS | CLI、schema 输入和 projection 消费者均覆盖 |
| D7 | 异常维度 | 已覆盖 | 全部 UC | 零写失败、权限拒绝、迁移错误、identity drift、fail closed 均覆盖 |
| D8 | 集成维度 | 已覆盖 | 全部 UC | Work、validation、state/current、context/ledger 边界明确 |
| Dx-01 | 审计与可追溯 | 已补充 | 全部 UC | 每项必须保留 source、revision、evidence/provenance 或失败来源 |
| Dx-02 | 发布血缘与消费者 | 已补充 | UC-PLAN-COMPILER～UC-PUBLISHED-ASSET-CONSUMER | 覆盖 package、closure、cost、SemVer、一次 qualification、freeze drift 和 clean-home canary |
<!-- coverage-checklist: end -->

## 附录：治理变更记录

| 版本 | 变更字段 | 旧值 | 新值 | 原因 |
|---|---|---|---|---|
| 1.0 | 产品基线 | 不存在 | `draft` | CR-071 要求新增产品基线；CP2 人工批准尚未发生 |
| 1.1 | CP2 review delta | V1 将 BL-001 延后，且缺少五项量化/恢复约束 | 在原 6 UC 上补齐 MF-2 硬前置、shared-core、v1 迁移、semantic-equivalence、单次 reprojection 和 CP4 inventory 追踪 | 响应 formal CP2 `changes_requested`；ID 与 formal gate 状态不变 |
| 1.2 | CR-072 Package 基线 | CR-071 的 6 UC / 18 REQ / 18 SCN / 12 Story 保持可追溯 | 追加 6 UC、12 REQ、12 SCN 和 12 产品 outcome Story；建立 Work A/B 单一 0.6.1 release lineage | CR-071 历史批准不重开；CR-072 于 2026-08-18 经 CP2 批准 |

## CR-073 增量场景（CP2 已确认）

| UC | 用户结果 | 关键边界 |
|---|---|---|
| UC-HISTORICAL-REFRAME | 区分可证明历史事实与未知历史，不伪造 CR-071 PASS | historical-reframe 只追加审计 binding；原始历史保留 |
| UC-WORK-INIT-PREFLIGHT | 写入前看到 contract/index/tuple/transaction 风险 | success/failure 双路径 zero-write；不得固化物理路径 workaround |
| UC-WORK-SCOPE-AMEND | paused/blocked Work 可追加合法 scope 并失效旧证据 | 只增不删、typed authorization |
| UC-FAILURE-RECOVERY | FAIL/observation 失败不再投影为健康 | orphan failure 必须 warning/block |
| UC-VALIDATION-TRUTH | 只复用环境与 manifest 未漂移的 PASS receipt | identity 漂移即 RUN 受影响层 |
| UC-VICTIM-REPLAY | 真实受害者证明六轮事故不重演 | source-candidate 需独立授权；installed-artifact 是下一发布硬门 |

| SGA | 推荐处理 | 状态 |
|---|---|---|
| SGA-073-01 historical reframe | 仅 `audited-known-historical-fact`，禁止补写 PASS | approved-2026-08-19 |
| SGA-073-02 source candidate | fixture 仅 provider contract；外部 replay 为 CP8 前必要项 | approved-2026-08-19 |
| SGA-073-03 installed artifact | 留作下一发布硬门，避免未授权安装/发布扩张 | approved-2026-08-19 |
| SGA-073-04 P7 边界 | STATE-CONTRACT、pause/resume、hard-gate 留 P7 | approved-2026-08-19 |
