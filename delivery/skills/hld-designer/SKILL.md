---
name: hld-designer
description: >-
  当需要将已确认需求转化为可评审、可决策、可交接的 High-Level Design（HLD）时使用。
  输出问题定义、候选架构方案对比、推荐方案、架构图、模块职责、技术选型、关键流程、
  非功能设计、风险、ADR 候选点和分阶段落地建议。兼容历史触发词：方案设计、架构设计、
  复杂度判定、设计方案、simple/standard/complex 判断。触发词包括：HLD、高层设计、架构评审、架构方案。
argument-hint: "可选：指定目标平台、技术栈约束或既有系统边界"
user-invokable: true
status: active
---

## 目标

基于已确认需求与场景输出 `docs/design/HLD.md`。正式写 HLD 前，先识别 `Architecture Gray Areas` 并输出 table-first advisor 输入；处于阶段委托时由 meta-se 直接与用户完成讨论，必要时再由 host-orchestrator 汇总 reviewer lane。HLD 完成后由 meta-se 使用 `checkpoint-manager` 生成 `process/checks/CP3-HLD-CONSISTENCY.md`，再由 host-orchestrator 汇总交还摘要、生成 CP3 Decision Brief，并在 `process/checkpoints/CP3-HLD-REVIEW.md` 中发起人工确认。

## 适用场景

- 需求已确认，需要进入正式高层设计
- 需要形成可评审、可交接、可作为 Story 拆解输入的设计文档

## 前置条件

- [ ] `docs/product/REQUIREMENTS.md` 已确认
- [ ] `docs/product/USE-CASES.md` 已确认

## 必须读取的输入

- `docs/product/REQUIREMENTS.md`
- `docs/product/USE-CASES.md`
- `process/REQUEST.md`
- `process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md`（若存在）
- `process/checks/CP2-DISCUSSION-CHECKPOINT.json`（若存在）
- 补充约束与参考资料（若存在）

## 知识来源

- 已确认的需求、场景和约束
- `skills/hld-designer/templates/HLD-TEMPLATE.md`
- `AGENTS.md` 中的阶段门控与下游设计需求

## 执行步骤

1. 输出问题定义、目标、约束与非目标。
2. 识别 `Architecture Gray Areas`：从已确认需求、场景、NFR、交付约束和 CP2 讨论结果中找出 3-4 个会改变架构形态、模块边界、验证策略、权限安全或维护成本的关键灰区。
3. 输出 table-first advisor 输入，表头固定为：`Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch`；处于 `delegated_interaction.phase=solution-design` 时，由 meta-se 直接与用户讨论并记录选择。
4. 读取用户选择或 host-orchestrator 汇总后的 reviewer lane 结果，再给出至少 2 个候选方案并完成显式比较；若需要 reviewer 子 agent 但平台当前无法真实拉起且未获 inline fallback 批准，必须把 HLD 前置讨论标记为阻断或 `N/A` 原因，不得伪造多角色意见。
5. 明确推荐方案、关键架构图、模块职责、技术选型、风险、适用条件、优化项、牺牲项和切换条件。
6. 执行 Use Case → Architecture Traceability，并至少用 2-3 个关键 UC 做场景模拟；模拟失败时不得进入 CP3 人工确认。
7. 为 CP3 Decision Brief 输出候选方案取舍摘要和 `decision_items`，覆盖用户意图匹配度、实现复杂度、可验证性、维护成本、平台兼容、安全 / 权限风险、交付影响、适用条件、切换条件和回退点；每个需要用户确认的架构 / 范围 / 风险接受项都必须包含推荐方案、至少 1 个备选方案（优先 2 个）和优劣分析。
8. **应用 HLD 拆分检查**：按 §"HLD 拆分原则"评估当前设计是否应拆为多份 HLD；若应拆，先完成拆分再继续。
9. 生成 `docs/design/HLD.md`（及拆分出的同级 HLD 文件）。不得自行跳过 HLD 前置讨论、CP3 自动预检、多角色讨论和人工确认。

## Architecture Gray Areas 子流程

1. 灰区来源必须显式引用 `USE-CASES.md`、`REQUIREMENTS.md`、NFR、交付路由、平台约束、CP2 discussion log / checkpoint 或输入材料。
2. 每个灰区必须说明为何影响 HLD 形成，而不是只列出待确认问题。
3. advisor discussion 使用已有角色，不新增 canonical agent：
   - `lane-product`：用户价值、场景适配、成功指标、范围取舍
   - `lane-architecture`：模块边界、演进路径、ADR、依赖关系
   - `lane-quality`：质量属性、安全、失败路径、验证与安装风险
   - `lane-docs`：可解释性和维护可读性作为检查项纳入汇总，不默认新增一次子 agent 调度
4. advisor lane 输出必须优先使用以下表格：

| Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch |
|---|---|---|---|---|---|
| <候选> | <优势> | <代价> | <范围 / 模块 / 数据 / 安全 / 验证 / 文档> | <推荐 / 不推荐 / 条件推荐> | <假设与切换条件> |

5. 讨论日志建议写入 `process/discussions/CP3-HLD-DISCUSSION-LOG.md`，恢复点建议写入 `process/checks/CP3-DISCUSSION-CHECKPOINT.json`。日志用于审计和恢复，不作为下游唯一输入；下游正式消费仍以 `HLD.md`、`ARCHITECTURE-DECISION.md`、Decision Brief 或必要的 `HLD-CONTEXT.md` 为准。
6. HLD 必须记录哪些讨论输入影响了推荐方案，哪些想法被延后，以及何时切换到备选方案。
7. 若某个架构灰区看似只有一个业务可行方案，也必须给出至少一个治理备选（保持现状、缩小范围、延后 Spike 或回退需求），供 host-orchestrator 在 CP3 待人工决策清单中呈现。

## HLD 拆分原则

> 一份 HLD 应只围绕**一个核心产物**展开。当一个设计会议同时涵盖多个产物或跨越多个治理层时，必须拆分成多份 HLD，各自独立评审、确认与 Story 拆解。

### 判定信号（满足任一即须考虑拆分）

1. **核心产物 > 1**：文档同时在设计 Skill / Agent / Workflow / 跨 Agent 机制中的两个及以上独立产物。
2. **职责跨层**：文档同时规定了"某产物的内部行为"与"host-orchestrator / 全局编排机制"；后者应独立立项。
3. **Story 数量超阈**：按当前设计拆出的 Story 数 > 5，且可明显按产物归组。
4. **ADR 明显分簇**：ADR 能按"产物 A 相关"与"产物 B 相关"清晰聚类，彼此引用少。
5. **交付顺序可独立**：两个产物可分别上线、彼此不强依赖（或只存在字段级依赖）。
6. **评审者分派差异大**：如果你要给不同子集指派不同的评审者与不同的严重度定义，信号强烈。

### 判定反信号（倾向保持单份）

1. 两部分共用同一套 ADR 或同一数据模型，拆开后需要双向引用。
2. 合计 Story ≤ 4，且强耦合、必须同一 Wave 交付。
3. 其中一部分不足以独立提出"问题定义 / 目标 / 成功标准"，只是配套说明。

### 拆分执行约束

- 拆分后每份 HLD 必须**独立完整**：独立的问题定义、目标、方案对比、ADR、Story 清单与确认记录。
- 原 HLD 的 frontmatter 追加 `companion_hld:` 列表；新 HLD 的 frontmatter 追加 `split_from:` 字段，写明源文件 + 源章节锚点。
- 拆分发生在哪一版，**原 HLD 修订记录必须新增一行**，列出被迁出的具体章节号、ADR 编号与 Story 编号。
- 拆分后，**上游字段（如 governance_mode）的生产者**留在产物 HLD；**字段的消费机制**归入治理/机制 HLD。
- 拆分不得破坏追溯链：在两份 HLD 的 §"与 xxx 的关系"或 §"非目标"中互相点名，说明谁不做什么。
- 若评审中临时决定拆分，使用 CR 单走流程，更新 `process/changes/` 并同步两份 HLD 的 frontmatter。

### 拆分依据的记录位置

- frontmatter：`companion_hld` / `split_from`
- 修订记录表：列出迁出的章节号 + ADR 编号
- 正文非目标章节：互相点名
- 若存在多份 companion，末尾补"§xx 与相关 HLD 的关系"表

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| HLD 过程稿 | `docs/design/HLD.md` | `skills/hld-designer/templates/HLD-TEMPLATE.md` |
| HLD 讨论日志 | `process/discussions/CP3-HLD-DISCUSSION-LOG.md` | 人类审计和恢复；由 host-orchestrator 汇总 |
| HLD 讨论恢复点 | `process/checks/CP3-DISCUSSION-CHECKPOINT.json` | 中断恢复；缺失时 CP3 自动检查必须说明 N/A 或阻断原因 |
| CP3 自动预检结果 | `process/checks/CP3-HLD-CONSISTENCY.md` | 由 `checkpoint-manager` 生成 |
| CP3 人工审查稿 | `process/checkpoints/CP3-HLD-REVIEW.md` | 由 host-orchestrator 基于 `checkpoint-manager` 生成 |

## 约束

- 输出必须遵循 `skills/hld-designer/templates/HLD-TEMPLATE.md`
- 标准模式下必须执行 `Architecture Gray Areas`；若判定不适用，必须在 CP3 自动检查或 HLD 自审中说明 `N/A` 原因
- 多角色讨论结果必须区分“方案形成输入”和“HLD 后评审意见”，不得只做事后评审
- 未确认前不得继续 Story 拆解
- 不下沉到类、函数或字段级实现设计

## 验收标准

- [ ] HLD 覆盖规定章节
- [ ] 至少 2 个候选方案已完成比较
- [ ] 推荐方案、风险和待确认问题明确
- [ ] HLD 前已记录 Architecture Gray Areas、advisor table-first 输入、discussion log / checkpoint 或 N/A 原因
- [ ] HLD 包含适用性矩阵、Use Case → Architecture Traceability、关键场景模拟、优化 / 牺牲 / 切换条件和自审记录
- [ ] 已应用 §"HLD 拆分原则"判定信号进行评估；若有拆分信号，已完成拆分并在 frontmatter 与修订记录中留痕

## 不适用边界

- 当前需要的是 LLD 或代码实现设计
- 需求尚未确认

## Gotchas

- 候选方案不能只是一个方案换不同措辞，必须有真实权衡差异
- 推荐方案若缺少适用边界说明，后续 Story 拆解很容易失真
- **Architecture Gray Areas 必须前置**：只在 HLD 写完后收集意见会错过影响方案形态的关键分歧
- **advisor table 不是装饰**：每个候选必须写清 Pros / Cons / Impact Surface / Recommendation / When to switch，避免只输出单一结论
- **场景模拟失败必须阻断**：关键 UC 无法走通推荐架构时，不得把问题推给 Story 拆解阶段
- **忽视拆分信号的代价很高**：把"某产物 + 某全局机制"压进一份 HLD，后续评审者会同时面对两种抽象层，容易陷入口径漂移
- **不要只在结尾补 companion_hld**：拆分必须反写 §非目标、§修订记录与 ADR 集合，否则追溯链不闭环
