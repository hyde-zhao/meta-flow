---
status: draft
version: "1.1"
confirmed_by: ""
confirmed_at: ""
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
total_use_cases: 6
formal_cp2_status: pending
---

# CR-071 使用场景基线

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 | 文档处理方式 |
|---|---|---|---|---|
| 1.0 | 2026-08-15 | meta-pm | 为 MF-1～MF-6 建立初始场景基线 | 按 CR-071 文档处理决策新增；正式 CP2 确认待定 |
| 1.1 | 2026-08-15 | meta-pm | 吸收 CP2 changes_requested 六项增量 | 保留 6 个 UC；formal CP2 仍 pending |

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
| 场景主体 | 已回答，待 CP2 正式确认 | 用户最新 freeform；`process/works/CR-071-R2/REQUEST.md` |
| 交付出口 | 已回答，待 CP2 正式确认 | Meta Flow 本体边界；CR-071 文档处理决策 |
| 主选方案 | OPT-01 | 用户要求“继续完成 meta-flow 侧的改进点进行能力补齐” |

## Scenario Gray Areas

**讨论日志**：`process/discussions/CP2-CR071-DISCUSSION-LOG.md`

**恢复点**：`process/checks/CP2-CR071-DISCUSSION-CHECKPOINT.json`

| 灰区 ID | 问题 | 为什么重要 | 影响面 | 推荐讨论顺序 | 状态 | canonical refs |
|---|---|---|---|---:|---|---|
| SGA-01 | 本轮主体是 Meta Flow 六项能力，还是同时扩大到外部目标项目制度？ | 决定仓库边界、授权和真相源数量 | 范围、复杂度、验证、交付出口 | 1 | resolved-by-freeform | REQUEST、CR-071、SGQ-001 |
| SGA-02 | legacy 兼容期采用 read-old/write-new、双写还是硬切换？ | 决定迁移风险、诊断和退役成本 | 范围、验证、维护、后续门控 | 2 | quantified-recommendation-pending-gate | CR-071 验收标准 3/4、CP2-DQ-02、SM-06 |
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

## 使用场景列表

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
<!-- coverage-checklist: end -->

## 附录：治理变更记录

| 版本 | 变更字段 | 旧值 | 新值 | 原因 |
|---|---|---|---|---|
| 1.0 | 产品基线 | 不存在 | `draft` | CR-071 要求新增产品基线；CP2 人工批准尚未发生 |
| 1.1 | CP2 review delta | V1 将 BL-001 延后，且缺少五项量化/恢复约束 | 在原 6 UC 上补齐 MF-2 硬前置、shared-core、v1 迁移、semantic-equivalence、单次 reprojection 和 CP4 inventory 追踪 | 响应 formal CP2 `changes_requested`；ID 与 formal gate 状态不变 |
