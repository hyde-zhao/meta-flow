"""工作区初始化模板。

模板保持短小：`mf init` 只负责生成骨架，具体项目规范由 manager 在
contracts/standards/ 中继续定制。
"""

ROOT_CLAUDE = """# Meta Flow 工作区（维护者）

你是 `meta-maintainer`。当前目录是工作区根目录。

## 职责

- 初始化、维护 `contracts/` 与 `deliveries/` 两个仓库。
- 安装、升级 CLI 与角色文件。
- 运行 `mf doctor`、`mf status`，维护 `mf.workspace.yaml`。
- 在 meta-flow 工具源码仓维护 CLI、模板、agent、测试与发布。

## 边界

- 不写需求、路标、任务卡、验收记录。
- 不写任何交付库源码。
- 不执行 `mf req`、`mf roadmap`、`mf task accept`。

## 目录角色

- 工作区根目录：`meta-maintainer`
- `contracts/`：`meta-manager`
- `deliveries/**`：`meta-worker`

进入其他目录时，以该目录的 `CLAUDE.md` / `AGENTS.md` 为准。
"""

ROOT_AGENTS = """# Meta Flow 工作区（维护者）

你当前以 `meta-maintainer` 身份工作。

- 只维护工作区骨架、角色文件、CLI 安装与跨仓健康。
- 不写需求、路标、任务卡、验收记录，不写交付库源码。
- `contracts/` 归 `meta-manager`，`deliveries/**` 归 `meta-worker`。
- 常用命令：`mf role`、`mf status`、`mf doctor`、`mf upgrade`。
"""

CONTRACTS_CLAUDE = """# 契约库（项目管理者）

你是 `meta-manager`。当前目录是契约库。

## 职责

- 与用户对接需求，维护 `REQ-*` / `CHG-*`。
- 在 P1 生成 PROJECT-PLAN、版本计划、阶段计划、初始化清单与模板目录。
- 维护路标、版本、阶段；组织 P1–P5。
- 维护 16 份规范。
- 编排设计、任务卡、wave、验收；维护分层验证与追踪矩阵。
- 维护系统架构、ADR、端到端规格与跨库契约。
- 默认读 `state/current.json` 与当前版本相关文档；历史归档默认不读。

## 边界

- 不直接写交付库源码；通过任务卡驱动 worker。
- worker 自验不等于验收；你必须独立复核自动项、抽查证据。
- 验收标准在任务卡创建时写定，事后不得追加。
- 交付库之间只通过契约库通信。

## 常用命令

`mf status`、`mf req ...`、`mf roadmap ...`、`mf phase ...`、`mf task ...`、`mf release freeze`
"""

CONTRACTS_AGENTS = """# 契约库（项目管理者）

你当前以 `meta-manager` 身份工作。

- 只读写 `contracts/`；不读交付库源码，只消费 `mf` 固化的证据与元数据。
- 维护需求、路标、阶段、规范、任务卡与验收记录。
- 任务卡是 worker 的唯一入口；验收必须独立于 worker 自验。
- 常用命令：`mf req`、`mf roadmap`、`mf phase`、`mf task`、`mf release`。
"""

DELIVERIES_CLAUDE = """# 交付库（执行者）

你是 `meta-worker`。当前目录是交付库集合。

## 职责

- 只领取任务卡，不主动扩展范围。
- 在任务卡 `allowed_paths` 内执行。
- 任务卡缺目标、输入、交付物、验收、路径、依赖时 BLOCKED，不猜。
- 只读 `state/current.json` 与任务包；不读完整契约、其他交付库、归档。
- 完成自验、开发记录与交接文件，用 `mf task submit` 提交。

## 边界

- 不改契约库、路标、需求、阶段或验收标准。
- 不跨交付库；共享接口通过契约库。
- 不直接问用户；问题写进交接文件的“未决问题”。
- 不自行验收。

## 常用命令

`mf task show <id> --packet`、`mf task start <id>`、`mf task submit <id> --handoff ...`
"""

DELIVERIES_AGENTS = """# 交付库（执行者）

你当前以 `meta-worker` 身份工作。

- 只处理分配给自己的任务卡；只写 `allowed_paths`。
- 不读契约库全文，只读 `mf task show --packet` 返回的任务包。
- 先确认任务就绪；缺关键字段时 BLOCKED。
- 完成实现、测试、开发记录和交接后提交，等待 manager 验收。
- 常用命令：`mf task show`、`mf task start`、`mf task submit`。
"""

STANDARDS = {
    "VERSION.md": """# VERSION — 版本与路标规范

## 双轨

- 工具：SemVer，例如 `v1.0.0`。
- 项目：路标 `R{n}` ↔ 项目版本 `n.x.y`。
- 交付库：各自 `delivery.yaml` 记录 SemVer；版本策略由 `project.yaml.version_policy` 决定：`same-major`（R1 默认）、`exact`、`independent`（R2）。
- meta-flow 自身交付物是 CLI 包，版本 = 工具 SemVer；`deliveries/` 只用于被管理项目。

## 映射

| 路标 | 默认版本范围 | 首发 | 声明方式 |
|---|---|---|---|
| R0 | 0.x.y | 0.1.0 | `version_major`/`version_range` 可声明项目映射（如 V1/R0=1.0.x） |
| R1 | 1.x.y | 1.0.0 | 同上 |
| R2 | 2.x.y | 2.0.0 | 同上 |

## 规则

- 破坏性变更 → 新路标，MAJOR + 1。
- 兼容新增 → 同路标 MINOR + 1。
- 修复 → PATCH + 1，不新开路标。
- 阶段预发布：`alpha`（P3）、`beta`（P4）、`rc`（P5）。
- 外部合同编号（如 `V01R01C00`）只写入发布说明，不作为内部真相。

`mf release freeze` 默认按 `ROADMAP.yaml` 的 `version_major`（或 `version_range`）校验；未声明时才回退 `R{n}=MAJOR`。声明映射允许 R0/V1 1.0.x 这类项目版本策略；未声明的 MAJOR 不一致默认拒绝，`--force` 必须记录 `--reason`、`--approved-by` 与版本。
""",
    "PROJECT.md": """# PROJECT — 项目计划与初始化规范

## 初始化必须产出

- `PROJECT-PLAN.md`：目标、成功指标、最终交付件与能力、交付库、过程计划、能力地图、风险。
- `INIT-CHECKLIST.md`：初始化逐项确认。
- `ROADMAP.yaml` + `R{n}-PLAN.md`。
- 需求基线、P1–P5 阶段计划。
- 验证计划：L1/L2/L3 分层、证据、追踪矩阵。
- `contracts/templates/` 模板目录。

## 初始化检查

1. 目标、范围、非目标、成功指标确认。
2. 交付库与 `version_policy` 确认。
3. 路标与版本计划确认。
4. 需求满足 DoR。
5. 阶段计划与退出条件确认。
6. 验证分层与证据要求确认。
7. 任务就绪与验收规则确认。
8. 术语/偏好记录到 KNOWLEDGE。
9. 用户确认；`mf doctor` 通过。

## 变更

项目计划变更走 `CHG-*`；P1 后变更需用户确认。
""",
    "ROADMAP.md": """# ROADMAP — 路标与版本计划规范

## 路标

`R{n}` 拥有主版本 `n`。字段：目标、范围、非目标、进入/退出条件、版本目标、REQ、风险。

## 版本计划表

`R{n}-PLAN.md` 包含：

- 版本目标与成功指标
- 里程碑
- P1–P5：目标、时间、负责人、过程交付件、退出条件
- 交付库/工作流依赖
- 风险与假设

## 阶段计划

每阶段进入前生成 `PHASE-PLAN`：目标、入口条件、模块/规格范围、WBS、任务/wave、过程交付件、决策清单/未决项、验证计划、时间、风险、退出条件。P4 阶段计划必须含需求聚类验收与单条 REQ 状态双轨；P5 必须含发布固定工作清单。

## 关闭与刷新

P5 结束：`mf roadmap close` → 关闭报告 → 未完成项转 R2/backlog → R2 计划 → 用户确认。
""",
    "DESIGN.md": """# DESIGN — 设计与规格规范

## 规格 SPEC

模板 `contracts/templates/SPEC.md`。必含：背景、范围/非目标、需求（EARS/Given-When-Then）、接口、数据、验收场景、非功能、依赖、开放问题、追踪。

每条规格必须关联 REQ；规格是 L2 设计验证的对象。

## 设计 DESIGN

模板 `contracts/templates/DESIGN.md`。必含：上下文、模块、接口、数据、流程、异常、非功能、方案对比、风险、ADR、测试策略、迁移/回滚。

## 设计包 DP（designer）

模板 `contracts/templates/DESIGN-PACKAGE.md`。必含：信息流、子项目/职责/交互/接口、
模块/功能/接口、REQ/MFP→SPEC→子项目/模块映射、跨子项目验证计划、预研计划、
风险/决策与 manager 设计验收。每条 REQ 至少一个 SPEC，无孤儿。

## ADR

模板 `contracts/templates/ADR.md`。决策、背景、备选、后果、状态。

## 质量

可实施、可测试、无未决冲突；高风险设计必须独立 `review` 任务。
""",
    "CONTEXT.md": """# CONTEXT — 读写范围与上下文控制规范

## 文档分层

- A 长期共享真相：project/roadmap/requirements/architecture/specs/standards/knowledge。
- B 当前版本工作集：当前 R 的 tasks/dev-records/verification/handoffs/bugs/phase plans/reports。
- C 冷历史：`archive/R{n}/`，默认不读。
- D 热状态：`state/current.json`，≤8KB，只存指针/计数。
- E 审计日志：`ledger.ndjson`、`READ-LOG.ndjson`，仅追加。

热区：state、当前阶段 PLAN 摘要、活跃 REQ/SPEC/矩阵、任务卡、活跃 BUG/MFP、REVIEW/证据索引、KNOWLEDGE 摘要。
暖区：PROJECT-PLAN、ROADMAP/版本 PLAN、规范、设计文档、上一阶段 REPORT。
冷区：archive、已完成任务、关闭 BUG/MFP、历史 PLAN/REPORT、LESSONS 全量。

## 角色读写矩阵

| 角色 | 热区 | 暖区 | 冷区 | 写 |
|---|---|---|---|---|
| manager | 预算内全读 | 按需 | 仅 `mf archive show --reason` | contract A/B；不写交付库源码 |
| worker | 任务包 + 活跃任务 bundle | 相关规格/接口/矩阵切片、allowed_paths | 禁止 | allowed_paths + 任务 bundle 流程文件；本地副本与 MFP 见下 |
| maintainer | 工作区/MFP/源码相关 | 按需 | 禁止项目内容 | meta-flow 源码/全局模板 |

worker 允许写 `.meta-flow/handoffs/<task>.md`、`.meta-flow/dev-records/<task>.md`（仅当前任务）与 `.meta-flow/improvements/MFP-*.yaml`（审计）；其他 `.meta-flow/**` 仍拒绝。

## 任务包

`mf task show --packet` 只含任务卡、inputs 片段、allowed_paths、must_read/may_read/do_not_read、budget、packet_digest。

## 工作区

- 版本：`roadmap/R{n}/`
- 阶段：`roadmap/R{n}/phases/P{m}/`
- 任务：`.../tasks/T{id}/`
- 阶段切换只读 `HANDOFF-TO-P{next}.md`；版本切换只读 `HANDOFF-TO-R{next}.md`。
- 任务 bundle 是跨角色唯一接口。

## Manager 读取

- 热区：`state/current.json`、`PROJECT-PLAN`、`ROADMAP.yaml`、当前 `R/PLAN.md`、需求索引、架构索引、`KNOWLEDGE.md`、`CONTEXT-POLICY`。
- 当前阶段：`phases/P{current}/PLAN.md`、活跃任务索引、上一阶段 handoff。
- 按需：任务引用的 REQ/SPEC/DESIGN、当前阶段验证/评审/缺陷详情。
- 冷区：上一阶段/更早阶段的完整过程、`archive/R{older}/`、未引用的完整文档；只有 `mf context expand --reason` 才读。

## Worker 读取

- 实现任务：`mf task show --packet` + 自己的任务 bundle + 自己子项目 `allowed_paths` 源码/测试。
- 评审任务：`mf task show --review-packet` + review_scope 内源码；review_scope 内任意大小文件可 Read 或 `mf context expand` 只读补读，不受 64KB 预算限制；review_scope 外仍拒绝。
- 返工：原任务 bundle + `review.md` + `review-handoff.md`。
- 禁止读其他子项目、归档、完整路标/需求/架构。
- 任务包 must_read 中的契约基线文件（TASK.yaml、REQ、SPEC、标准、BUG、MFP）可 `mf context expand --reason packet_missing` 只读补读并写 READ-LOG；非 must_read 仍拒绝。

## 热状态

`current.json` 只存指针/计数；TASK.yaml + ledger 是任务真相，state 是派生快照；禁止手工编辑 state；`mf doctor` 做状态对账，`mf state rebuild` 可安全重建；超 8KB 由 `mf doctor` 报错。

## 归档

版本关闭后 B 层移入 `archive/R{n}/`；长期共享文档原地保留，更新 status/roadmap/supersedes；活动文档不得引用归档。

## 读扩展

`mf context expand <path> --reason <packet_missing|field_conflict|schema_validation_failed|human_audit|summary_insufficient>`；写 READ-LOG。只读命令不得被判定为写入；契约基线 must_read、评审 review_scope、任务 bundle 与 allowed_paths 是白名单，其余仍拒绝。

## 检查

`mf doctor` 校验策略文件、state 大小、归档边界、未授权读。
""",
    "REQUIREMENTS.md": """# REQUIREMENTS — 需求与变更规范

## REQ

每个需求必须有稳定 ID、来源、优先级、状态、所属路标与可验收条件。

```yaml
id: REQ-0001
title: ...
priority: must        # must|should|could
status: accepted      # proposed|accepted|in_roadmap|in_progress|verified|released|deferred
roadmap: R1
acceptance: [...]
```

## 需求质量（DoR）

- 单一、明确、可验收；有来源、优先级、范围、非目标、依赖。
- 验收标准可执行/可观察；禁止“优化”“更好”等不可判定词。
- 每条需求关联路标、规格、任务、验证。
- 不满足 DoR 不得进入 P1 基线。
- 模板：`contracts/templates/REQUIREMENT.md`。

## 追踪

`mf req trace REQ-0001` 输出：

```text
REQ-0001 → R1 → SPEC/DESIGN → TASK → DEV-RECORD → VR-L1/L2/L3 → BUG → RELEASE
```

## 变更

基线后变更使用 `CHG-{序号}`，写明原因、影响范围、受影响 REQ/SPEC、决策与批准人。

## 路标关闭

所有 REQ 必须为 `verified`、`released` 或 `deferred`（附原因），否则不能关闭路标。
""",
    "PHASE.md": """# PHASE — 五阶段规范

每个阶段必须写清：**输入、输出/过程交付件、任务拆解规则、验证规则、退出条件**。
任务粒度按“可独立验证的增量”划分，不按文件或命令机械拆分。

## 阶段总览

| 阶段 | 目标 | 输入 | 输出/过程交付件 | 验证规则 | 退出条件 |
|---|---|---|---|---|---|
| P1 计划 | 端到端计划与需求基线 | 用户需求、路标草案 | PROJECT-PLAN、REQ 基线、版本 E2E 计划、P1–P5 计划 | 需求 DoR、E2E 场景覆盖检查 | 用户确认；需求覆盖路标范围 |
| P2 设计 | 规格与架构基线 | REQ 基线、E2E 计划 | SPEC、DESIGN、ADR、规格-模块矩阵 | L2 设计评审、接口/数据契约、矩阵完整性 | 设计评审通过；接口/数据/测试设计可实施 |
| P3 实施 | 按模块交付 | SPEC/矩阵、模块设计 | 模块任务卡、代码与测试、跨模块验证任务 | L1 单测/lint、L2 契约测试、跨模块规格验证 | 所有任务 PASS 或 WAIVED；无阻塞缺陷 |
| P4 试运行 | 端到端验证与用户试用 | P3 交付、E2E 计划 | 聚类验收记录、单条 REQ 状态表、回归证据 | L3 E2E/UAT、回归、缺陷门禁 | 回归通过；用户试用通过；缺陷关闭/接受 |
| P5 发布 | 发布与归档 | P4 验收、发布清单 | 冻结清单、发布说明、用户手册、安装/升级 smoke、归档 | 发布一致性校验、smoke、归档索引 | 发布清单完成；版本冻结；用户批准；路标刷新 |

## P1 计划

- 输入：用户需求、项目目标、路标草案。
- 输出：`project/PROJECT-PLAN.md`、需求基线（REQ + DoR）、**版本 E2E 计划**（用户旅程/功能域/风险）、P1–P5 阶段计划、Roadmap 刷新记录。
- 任务拆解规则：按需求聚类与用户旅程拆解，不按文件拆；每条 REQ 至少关联一个 SPEC/任务计划。
- 验证规则：DoR 全部通过；E2E 场景覆盖全部 must REQ。
- 退出：用户确认 P1 计划与需求基线。

## P2 设计

- 输入：REQ 基线、版本 E2E 计划。
- 输出：`specs/SPEC-*.md`、`architecture/DESIGN-*.md`、ADR、**规格-模块矩阵**（模板 `SPEC-MODULE-MATRIX.md`）。
- 任务拆解规则：先识别模块与接口，再把规格映射到模块；**一个规格可落多个模块，一个模块可承载多个规格**；跨模块规格必须生成独立验证任务，不得只挂在某一模块任务里。
- 验证规则：L2 设计评审；矩阵每行有主责/参与模块、接口契约与验证任务；规格无归属或验证任务缺失视为未完成。
- 退出：设计评审通过；接口/数据/测试设计可实施；矩阵完整。

## P3 实施

- 输入：SPEC/矩阵、模块设计、接口契约。
- 输出：按模块编排的 TASK 卡（字段含 `module`、`spec_ids`、`verification`/`evidence`）、代码与测试、跨模块验证任务、L1/L2 证据。
- 任务拆解规则：每个任务是一个**可独立验证的增量**；同一模块内按规格/接口切分；跨模块规格单独建 `verify` 任务；依赖显式、wave 内无写冲突。
- 验证规则：每个 acceptance 绑定验证方式（automated/artifact/demonstration/metric）与命令或证据路径；每个 BUG/MFP 至少一个自动化用例（含负向/安全）；L2 契约测试覆盖矩阵。
- 退出：所有任务 PASS 或 WAIVED；无阻塞缺陷；跨模块规格验证任务通过。

## P4 试运行

- 输入：P3 交付、E2E 计划、回归清单。
- 输出：**需求聚类验收记录**（按用户旅程/功能域/风险聚类）+ **单条 REQ 状态表**（双轨，聚类不替代逐条状态）；回归与试用证据。
- 任务拆解规则：按需求聚类组织验收任务；同一聚类内复用 E2E 场景，不逐条重复造场景。
- 验证规则：L3 E2E/UAT + 回归；聚类覆盖矩阵逐项勾选；单条 REQ 状态逐条更新（verified/released/deferred 附原因）。
- 退出：回归通过；用户试用通过；缺陷关闭/接受；用户确认 P4。

## P5 发布

- 输入：P4 验收、发布清单。
- 输出：发布固定工作清单（release freeze、发布说明、用户手册、安装/升级 smoke、归档、P5 门禁）、发布记录。
- 任务拆解规则：发布固定工作清单每项一任务或显式勾选；修复类任务按 BUG 优先级排列；不新增功能需求（新需求进入下一路标或 CHG）。
- 验证规则：`mf release check`、安装/升级 smoke、归档索引检查、P5 门禁（open blocker/critical=0）。
- 退出：发布清单完成；版本冻结；用户批准；路标刷新。

## 阶段计划

每阶段进入前生成 `roadmap/R{n}/phases/P{m}/PLAN.md`：目标、入口、模块/规格范围、WBS、任务/wave、过程交付件、**决策清单/未决项**、验证计划、时间、风险、退出条件。模板 `PHASE-PLAN.md`。

## 用户门禁

- 必须：路标规划、P1 退出、P4 退出、P5 退出。
- 高风险/架构变更：P2 退出。
- P3 由 manager 逐卡验收，不打断用户；P4 按需求聚类批量验收一次。

## 阶段报告

退出时生成 `roadmap/R{n}/phases/P{m}/REPORT.md`：目标核对、需求聚类验收与单条 REQ 状态、L1/L2/L3 验证结果、决策日志摘要、缺陷、知识、下一阶段调整建议、路标影响、用户确认记录。

## 路标刷新

P5 结束后：`mf roadmap close R{n}` → `mf roadmap plan R{n+1}`。
""",
    "TASK-CARD.md": """# TASK-CARD — 任务卡规范

## 字段

任务卡是过程文件，按机器需要设计；人读视图由 `mf task show` 自动生成，不手工维护第二份。

- `id`：`R{路标}-P{阶段}-T{序号}`。
- `kind`：`implement|design|verify|document|review|fix`。
- `owner_role` / `executor_role`：责任主体与执行者分离；`design` 默认
  `owner_role=designer`/`executor_role=designer`，`implement|fix|document|verify`
  默认 `worker`，`review` 由未参与实现的独立评审者（worker 身份）执行。非默认主责需
  manager 显式确认（`--owner-confirmed-by`）并写 ledger；worker 不得冒充 designer，
  designer 只能执行 design 任务。
- `delivery`：所属交付库。
- `module`：主责模块（P3 起；跨模块规格填主责模块）。
- `spec_ids`：关联规格，可多个；跨模块规格必须另有独立验证任务。
- `wave`：并行波次。
- `depends_on`：前置任务。
- `inputs`：引用的 REQ/SPEC/DESIGN/标准/BUG/MFP。
- `allowed_paths` / `forbidden`：写路径边界。
- `deliverables`：交付物清单。
- `acceptance`：验收项（见 ACCEPTANCE）；每项绑定验证方式与命令/证据。
- `verification` / `evidence`：验证方式与证据路径（可选，按机器需要）。
- `handoff`：是否要求交接文件。

## 任务就绪标准（DoR）

1. 单一、明确的结果。
2. 输入已列出且存在。
3. 交付物路径/格式明确。
4. 验收项可执行/可判定；每个 acceptance 绑定验证方式（automated/artifact/demonstration/metric）与命令或证据路径。
5. `allowed_paths` / `forbidden` 明确。
6. 依赖已 accepted 或不存在。
7. 交付库有效，wave 内无写冲突。
8. 任务必须是**可独立验证的增量**；一次 worker 会话可完成，过大拆分。
9. 每个 BUG/MFP 至少一个自动化用例（含负向/安全）。
10. `risk` / `authorization` 已设置；`module` / `spec_ids` 与规格-模块矩阵一致（P3 起）。
11. 无未决澄清问题。

不满足不得 `ready`；worker 可 `BLOCKED` 并指出缺项。模板：`contracts/templates/TASK.yaml`。

## 责任主体与执行者映射

| kind | owner_role | executor_role | 说明 |
|---|---|---|---|
| design | designer | designer | manager 派发设计工作包；manager 验收 |
| implement/fix/document/verify | worker | worker | 子项目实现/自验 |
| review | worker | worker | 未参与实现的独立评审者 |

缺省由工具按 kind 推导；非默认主责必须 manager 显式确认并审计。

## 状态机

```text
draft → ready → in_progress → submitted → accepted | rejected
submitted → blocked → manager 裁决（改卡/扩 allowed_paths/CHG/新卡）→ rework | rejected
submitted → rework（review NEEDS_REWORK，整改项在原 acceptance/scope 内；自动/一键重开）
rework → in_progress（worker 用 mf task rework 开始，记录 review/整改项/lease）
rejected → rework | in_progress（manager 裁决返工；review NEEDS_REWORK 时必须用 mf task rework）
```

BLOCKED 交接（`结论：BLOCKED` 或 `mf task submit --blocked`）不得自动推进独立评审，转为 manager 裁决；评审任务保持 draft/ready，不派给评审者。

## 并行

- 同一 wave 内不得写同一路径。
- 不同交付库天然可并行。
- `verify` / `review` 必须派给未参与实现的 worker。
- 跨模块规格验证任务可读取多个模块的 allowed_paths，评审范围按 review_scope。

## 禁止

- worker 不得修改验收标准。
- manager 不得事后追加验收项；返工开新卡或 `CHG-*`。
""",
    "ACCEPTANCE.md": """# ACCEPTANCE — 验收规范

## 原则

1. 验收标准前置，任务卡创建时写定。
2. 每项可判定：方法、命令、期望、证据；每个 acceptance 绑定 `method` 与 `command`/`evidence`。
3. worker 自验只作为提交证据；manager 必须独立复核。
4. 提交时校验 diff 是否在 `allowed_paths` 内；`blocked` 提交转 manager 裁决，不进入验收。
5. 每条结果绑定证据 digest；证据缺失不得 PASS。
6. 结论只能是 `PASS / PASS_WITH_RISK / NEEDS_REWORK / BLOCKED`。
7. `PASS_WITH_RISK` 必须写风险、影响、接受人。
8. 阶段验收 = 任务验收汇总 + 阶段目标核对 + 开放风险 + 用户确认。
9. 每个 BUG/MFP 至少一个自动化用例（含负向/安全），不能只有高层条目。
10. 一任务一 commit：不同 MFP/BUG/任务不得混在同一提交（维护批次按 MFP 拆分）。
11. 连续两轮出现同类安全绕过：暂停返工，回到设计/威胁模型，结论 BLOCKED 并记录决策，不得继续叠加补丁。
12. 高/关键安全任务必须有 `SECURITY-CARD.md`（信任边界/攻击者能力/fail_closed 可证明范围/不可防残余/风险接受人）与 `NEGATIVE-MATRIX.md` 用例。

## 方法

| 方法 | 适用 | 证据 |
|---|---|---|
| automated | 代码/CLI/schema | 命令、退出码、日志 |
| artifact | 文档/设计/配置 | 文件 + schema/内容检查 |
| demonstration | 用户可见行为 | 步骤 + 观察结果 |
| metric | 性能/覆盖率 | 指标报告 |

## P4 需求聚类验收（双轨）

- **聚类维度**：用户旅程、功能域、风险（安全/数据/兼容性）。
- **聚类覆盖矩阵**：`聚类 | 覆盖 REQ | E2E 场景 | 证据 | 结论`；同一聚类一次验收，不逐条重复造场景。
- **单条 REQ 状态表**：`REQ | 状态(verified/released/deferred/rejected) | 证据 | 原因`。
- 聚类验收不替代单条 REQ 状态：聚类 PASS 但单条 REQ 无证据时该 REQ 仍不得标记 verified。
- 模板：`PHASE-PLAN.md` 的“P4 需求聚类验收”与 `PHASE-REPORT.md` 的“单条 REQ 状态”。

## P5 发布固定工作清单

`[ ] release freeze；[ ] 发布说明；[ ] 用户手册；[ ] 安装/升级 smoke；[ ] 归档；[ ] P5 门禁（open blocker/critical=0，REQ 状态合法）`。
每项必须有证据路径；清单未完成不得 P5 退出。

## 独立性

高风险任务必须有 `verify` 或 `review` 任务，由另一个 worker 执行。

## Definition of Done

- 任务 DoD：实现 + 测试 + 开发记录 + 交接 + L1 证据；fix 任务含根因/修复/回归；文档任务含内容标准；BLOCKED 不算完成。
- 阶段 DoD：过程交付件齐全 + L1/L2（P3）/ L3（P4）+ 缺陷门禁 + 用户确认。
""",
    "DEVELOPMENT.md": """# DEVELOPMENT — 开发规范

## 范围

- 只改任务卡 `allowed_paths`。
- 不跨交付库；共享代码/接口先进入契约库。
- 不修改契约库、路标、需求、验收标准。

## 实现

- 每个任务至少包含实现与对应测试。
- 提交前运行任务卡中的自动验收项。
- 代码风格遵循交付库自身配置；没有配置时使用语言默认规范。
- 不提交凭据、构建缓存、本机路径。

## 开发记录

每个任务写任务 bundle 的 `dev-record.md`（canonical）：目标、设计引用、实现摘要、关键决策、变更文件、测试、偏差、限制、证据、handoff 引用。交付库本地副本路径统一为 `.meta-flow/dev-records/<task>.md`；`mf task submit` 优先读取 bundle `dev-record.md`，缺失时回退本地副本。

`mf task submit` 固化到任务 bundle；manager 作为 L1 证据审核。

## worker 遵守

- 读任务包、PROJECT-PLAN、相关 SPEC/DESIGN、TASK-CARD/DEVELOPMENT/VERIFICATION/ACCEPTANCE、KNOWLEDGE。
- 只写 `allowed_paths`；不写契约库；不跨交付库。
- 流程文件（handoff/dev-record/evidence）写入任务 bundle，由 packet 的 process paths 白名单授权，与 `allowed_paths`/`forbidden` 独立。
- worker 无交付根绑定时，任务命令必须用 `--project-dir` 指定交付库（否则 rc=3）。
- 先确认任务就绪；不清晰则 `BLOCKED`。
- 完成实现 + 测试 + 开发记录 + 交接再提交。

## 交接

完成后写任务 bundle 的 `handoff.md`（或交付库本地副本 `.meta-flow/handoffs/<task-id>.md`）：

1. 完成摘要
2. 变更文件
3. 验证结果（逐项对应 acceptance）
4. 缺陷
5. 纠正与经验
6. 未决问题
7. 下一步建议
8. 证据索引
9. fix 任务补充：根因、修复、回归证据
""",
    "VERIFICATION.md": """# VERIFICATION — 验证规范

## 分层验证

| 层 | 验证对象 | 要回答的问题 | 主要证据 | 门禁 |
|---|---|---|---|---|
| L1 实现 | worker 实现 | 代码是否正确、健壮、符合开发规范？ | 单测、集成、lint、build、开发记录 | task accept |
| L2 设计 | 设计规格 | 实现是否符合 SPEC/DESIGN/接口/数据契约？ | 契约测试、schema、接口测试、设计评审 | P3 退出 |
| L3 需求 | 原始需求 | 用户要的能力是否真的可用？ | 验收场景、E2E、UAT、演示 | P4/P5 退出 |

三层都要，不能互相替代；L1 通过不代表 L2/L3 通过。

## 验证记录

`VR-*` 字段：layer、scope、requirement_refs、design_refs、task_refs、method、result、evidence、bugs、verifier、date。

`mf verify record --layer implementation|design|requirement`。

## 追踪矩阵

`REQ → SPEC/DESIGN → 规格-模块矩阵 → TASK → 证据 → VR(L1/L2/L3) → BUG/MFP/CHG → RELEASE`。

`mf req trace` 输出上述链路并包含 BUG/MFP/CHG 关联；`mf req trace --check` 检测孤儿（无 SPEC/TASK/证据/VR 的 REQ、无 REQ/SPEC 的 TASK、未关闭且无修复任务的 BUG、无验收/证据的 MFP）并返回非零；阶段门/发布门用 `--all --check` 做一次性全量对账。

`mf doctor` 做状态对账：TASK.yaml（真相）+ ledger 与 `state/current.json`（派生快照）不一致时报警，`mf state rebuild` 可安全重建。

跨模块规格验证：矩阵中同一 SPEC 落在多个模块时，P3 必须生成独立 `verify` 任务，验证接口契约与跨模块行为；只跑单模块单测不视为 L2 通过。

## 证据

- 自动化：命令、退出码、输出日志。
- 文档/设计：文件 + schema/内容检查。
- 演示：步骤、观察结果、截图/录屏。
- 指标：报告、阈值、对比基线。

## 失败处理

- `NEEDS_REWORK`：回到当前任务；范围内整改项自动/一键重开为 `rework`，worker 用 `mf task rework <id>` 开始；范围外/新 acceptance/BUG/MFP/CHG 或争议由 manager 裁决。
- `BLOCKED`：写最小阻塞证据，停止当前任务，不转做其他任务。
- `PASS_WITH_RISK`：记录风险与接受人，进入后续决策。

## 回归

修复后只回归受影响层与任务卡声明的验收项，不重跑无关任务。
""",
    "BUGS.md": """# BUGS — 缺陷跟踪规范

## 记录范围

所有验证、试运行、用户反馈中发现的交付行为缺陷，必须记录为 `BUG-*`，存放 `contracts/bugs/`。

## 字段

- id、title、severity、status
- found_in：phase / task / verification
- delivery、related_reqs
- environment、steps、expected、actual、evidence
- fix_task、root_cause、changed_files、regression、resolution

## 生命周期

`open → triaged → in_progress → fixed → verifying → closed`；`closed → reopened`；`open/triaged → deferred/wontfix`（需理由和用户接受）。

## 联动

- `mf verify record --result FAIL` 必须关联 BUG。
- 修复用 `kind: fix` 任务，`fixes: [BUG-*]`。
- 交接必须含“根因 / 修复 / 回归证据”。
- P4/P5 门禁：open blocker/critical 阻止退出/发布。
- worker 在交接 `## 缺陷` 上报，manager 用 `mf bug add` 记录。

## 严重级别

blocker：无法继续；critical：核心功能不可用；major：主要功能受损；minor：轻微；trivial：文案/体验。
""",
    "KNOWLEDGE.md": """# KNOWLEDGE — 知识沉淀与纠正记录
## 记录什么

- `term`：术语纠正（错误用法 → 正确用法）
- `behavior`：行为纠正（触发 → 正确行为）
- `convention`：项目约定
- `preference`：沟通/格式/决策偏好
- `lesson`：阶段/版本复盘

## 存放

`contracts/knowledge/KNOWLEDGE.yaml`（真相）、`KNOWLEDGE.md`（渲染）、`LESSONS-R{n}.md`（版本复盘）。

## 谁记录

- manager 记录用户纠正。
- worker 在交接 `## 纠正与经验` 上报，manager 审核后合并。
- 条目必须有 source、日期、上下文。

## 注入

- manager 会话启动读取 KNOWLEDGE.md 摘要。
- `mf task show --packet` 注入相关术语/约定。
- SessionStart hook 打印最近纠正与开放 bug；hook 只注入，不做语义捕获。

## 总结

- `mf phase review` 增加“用户纠正与知识沉淀”章节。
- `mf roadmap close` 生成 `LESSONS-R{n}.md`。
""",
    "IMPROVEMENTS.md": """# IMPROVEMENTS — MFP 改进包规范

## 定位

`MFP-*` 是 **meta-flow 工具本身**的改进包，不是业务需求或任务。

## 角色

- manager：在 `contract/improvements/` 创建、补全，并 `mf improve submit` 到全局 inbox。
- worker：在 `.meta-flow/improvements/` 创建本地 MFP，写进交接；由 manager `mf improve import`。
- maintainer：读取 `~/.meta-flow/improvements/inbox/`，导入源码仓，分类并实施/关闭。

## 必填上下文

`title`、`problem`、`context.reproduction`、`context.expected`、`context.actual`、
`context.affected`、`acceptance`、`testing_plan`、`source`、`mf_version`、
`privacy.sanitized=true`。

不齐全只能停在 `draft`；`mf improve validate` / `submit` 会列出缺项。

## 生命周期

`draft → submitted → triaged → accepted → implementing → implemented → verified → closed`；
`rejected | deferred | duplicate` 需理由。

## 源码仓分类建议

| 情况 | 记录 | 处理 |
|---|---|---|
| 现有行为错误 | `BUG-*` | 已实现则记录版本/commit 并关闭 MFP；未实现则修复 |
| 新增能力 | `REQ-*` | 已实现则记录对应版本；未实现则进入源码改进队列 |
| 改变现有行为/模板兼容性 | `CHG-*` | 已实现则记录变更；未实现则进入源码改进队列 |

- 已实现的 MFP：在源码 `improvements/records/` 记录对应 BUG/REQ/CHG，MFP 移入 `closed/`。
- 未实现的 MFP：完整包复制到源码 `improvements/open/`，由 meta-flow 源码会话实施；完成后再记录并关闭。

## 存储

```text
<contract>/improvements/MFP-*.yaml
<sub>/.meta-flow/improvements/MFP-*.yaml
~/.meta-flow/improvements/inbox/<project-id>/MFP-*.yaml
<source>/improvements/{inbox,open,closed,records}/
```

## 验收

- 提出者写验收标准；maintainer 不得改写。
- maintainer 实施后，由提出者/用户/独立 reviewer 验证。
- `resolution` 记录版本、commit、测试证据、验证人。
""",
    "DELIVERY.md": """# DELIVERY — 交付规范

## 交付库

每个交付库包含：

- `delivery.yaml`
- `src/`、`tests/`、`release/`
- `RELEASE-NOTES.md`
- `USER-MANUAL.md`

## 最终交付件能力

manager 在 P1 的 PROJECT-PLAN 中登记每个最终交付件的能力、对应 REQ 与验收方式；P5 退出前逐项核对。交付库只保存自己的源码、发布件、发布说明和用户手册。

## 发布说明

至少包含：版本、日期、范围、变更、已知问题、升级/回滚说明、契约版本。

## 用户手册

至少包含：适用对象、安装/部署、快速开始、功能说明、故障排查。

## 跨库

- 交付库之间不直接引用。
- 共享接口/数据契约放 `contracts/specs/`。
- 发布说明引用契约 ID，不复制契约正文。

## 发布冻结

`mf release freeze` 记录项目版本、各交付库版本、契约版本、产物与证据 digest；冻结不等于发布授权。
""",
    "DECISIONS.md": """# DECISIONS — 决策分级与决策日志规范

## 目的

决策前置、人工节点最小化：把不确定项集中为决策门，一次性确认；小问题按技术判断自主决策并留痕，不频繁打断用户。

## 决策分级（D0–D3）

| 级别 | 名称 | 判定标准 | 决策人 | 记录 |
|---|---|---|---|---|
| D0 | 用户必决 | 需求语义、用户可见交互、重大方案/影响面、安全/合规边界、成本/进度重大影响 | 用户 | 决策门模板 + 阶段 PLAN/CHG/ADR |
| D1 | 用户确认影响 | 跨模块接口、数据模型、发布范围、影响多交付库的方案 | 用户确认（manager 提出） | 决策门模板 + CHG/ADR |
| D2 | 技术决策 | 实现细节、局部重构、测试策略、无用户可见影响的库选择 | manager/worker | 决策日志一行 + 任务卡备注 |
| D3 | 自动决策 | 格式化、lint、小依赖升级等无行为影响操作 | manager/worker | 审计日志/提交说明即可 |

判定顺序：先看是否用户可感知（D0）→ 是否跨模块/影响面大（D1）→ 是否影响实现方案（D2）→ 否则 D3。拿不准时升级一级。

## 决策门模板

```text
问题：
背景：
选项：A ... / B ... / C ...
默认值：
影响分析（需求/用户/模块/成本/风险）：
建议：
确认人：
日期：
结论：
```

模板文件 `DECISION-LOG.md`；完整示例写入阶段 PLAN 附录、CHG 或 ADR。

## 升级规则

出现以下任一情况必须升级到用户/manager 门，不得由 worker 自行决定：

- 需求变化或需求语义不清；
- 用户可见行为变化；
- 安全/合规/权限边界；
- 跨模块接口或数据模型；
- 成本/进度超过阈值；
- 评审或实施中存在争议。

## 决策日志

一行一条，放在阶段 PLAN 附录、CHG 或 ADR：`日期 | 问题 | 级别 | 选项 | 结论 | 影响 | 确认人`。可审计但不过度文档化；D2/D3 只记结论，不写长文。

## 阶段规则

- 设计阶段（P1/P2）尽量关闭决策；已知未决项不得拖到实施后。
- 实施阶段（P3）只处理新出现的重大项；其余走 D2/D3 并记录。
- 实施完成后收集不满足点，统一决策一次；只升级重大/用户关注项。
- 不新增每任务用户确认，不增加人工门数量。
""",
    "DOCUMENTATION.md": """# DOCUMENTATION — 文档规范

文档的目的是**控制每次任务读写区间、减少上下文预算**；首要保证需求/规格被正确实施，其次减少预算。冗余文档会消耗更多预算，必须合并或归档。

## 单一真相源

- 需求、路标、计划、状态、架构、设计、端到端契约：`contracts/`。
- 交付库只保存自己的源码、发布件、发布说明、用户手册。
- 跨库共享内容必须放契约库，其他文档引用 ID，不复制正文。
- 同一事实只能有一份“真相”文档；其他文档用“见 PLAN §X / SPEC-00Y / 证据路径”引用。

## 文档必要性矩阵

| 类别 | 文档 | 唯一真相 | owner | 读者 | 更新时机 |
|---|---|---|---|---|---|
| 必须保留 | PROJECT-PLAN | 是 | manager | 用户/manager/worker | init/P1；变更走 CHG |
| 必须保留 | ROADMAP.yaml + R{n}-PLAN.md | 是 | manager | manager/用户 | 路标规划/刷新 |
| 必须保留 | 当前阶段 PLAN（3–5 页） | 是 | manager | manager/worker | 阶段进入/调整 |
| 必须保留 | REQ + SPEC + 规格-模块矩阵 | 是 | manager | manager/worker | P1/P2 |
| 必须保留 | TASK.yaml（机器最小字段） | 是 | manager | manager/worker | 任务创建/状态变化 |
| 必须保留 | 验收证据（任务 bundle/ evidence、VR） | 是 | worker/verifier | manager/reviewer | 执行/验证 |
| 必须保留 | REVIEW（单文件） | 是 | reviewer | manager | 评审 |
| 必须保留 | 活跃 BUG/MFP 台账 | 是 | manager | manager/worker | 发现/关闭 |
| 必须保留 | 发布文档（交付库） | 是 | worker | 用户/manager | 发布 |
| 必须保留 | 阶段 REPORT（2–3 页，含经验摘要） | 是 | manager | 用户/manager | 阶段退出 |
| 必须保留 | HANDOFF（仅未决/next，半页） | 是 | worker | manager/reviewer | 任务提交 |
| 合并 | review-packet + review-handoff → REVIEW | — | reviewer | manager | 评审 |
| 合并 | dev-record + progress → 任务记录（仅长任务/批处理） | — | worker | manager | 执行 |
| 合并 | INIT-CHECKLIST → PROJECT-PLAN 附录/README 索引 | — | manager | manager | init |
| 合并 | 阶段 REPORT + LESSONS → REPORT 含经验摘要；版本关闭再生成 LESSONS-R{n} | — | manager | manager | 阶段/版本关闭 |
| 归档 | 已完成任务、关闭 BUG/MFP、历史 PLAN/REPORT、旧 handoff | — | manager | 按需 | 版本关闭 |

## 页数/字数上限与引用规则

- 任务卡 ≤1 页；REVIEW ≤1 页；handoff ≤半页；阶段 PLAN 3–5 页；阶段 REPORT 2–3 页。
- 禁止复制大段规范/计划/证据正文，使用引用（ID、章节、证据路径）。
- 超限退回或要求改为引用；`mf doctor` 检查热区文档大小。

## 热/冷区与角色读写

见 `CONTEXT.md`：热区（state、当前阶段 PLAN 摘要、活跃 REQ/SPEC/矩阵、任务卡、活跃 BUG/MFP、REVIEW/证据索引、KNOWLEDGE 摘要）；暖区（PROJECT-PLAN、ROADMAP/版本 PLAN、规范、设计、上一阶段 REPORT）；冷区（archive、已完成任务、关闭 BUG/MFP、历史 PLAN/REPORT、LESSONS 全量）。

- manager：热区预算内全读，暖区按需，冷区仅 `mf archive show --reason`。
- worker：只读任务包 + 相关规格/接口 + allowed_paths；超预算用 `mf context expand --reason`。
- maintainer：只读 MFP/源码相关。
- 阶段门全量对账一次；默认查询只含活跃项，`--all`/`--history` 才查冷区/全量。

## 类型与命名

| 类型 | 命名 |
|---|---|
| 需求 | `REQ-0001` |
| 变更 | `CHG-0001` |
| 规格 | `SPEC-<域>-001` |
| 设计 | `DESIGN-<域>-001` |
| 架构决策 | `ADR-0001` |
| 任务 | `R1-P3-T001` |
| 验证 | `VR-0001` |

## 制品与模板

| 制品 | 路径 | 模板 | 所有者 | 时机 |
|---|---|---|---|---|
| 项目计划 | `project/PROJECT-PLAN.md` | `PROJECT-PLAN.md` | manager | init/P1 |
| 初始化清单 | `project/INIT-CHECKLIST.md` | `INIT-CHECKLIST.md` | manager | init |
| 版本计划 | `roadmap/R{n}-PLAN.md` | `ROADMAP-PLAN.md` | manager | P1 |
| 阶段计划 | `roadmap/phases/R{n}-P{n}-PLAN.md` | `PHASE-PLAN.md` | manager | 阶段进入 |
| 阶段报告 | `roadmap/phases/R{n}-P{n}-REPORT.md` | `PHASE-REPORT.md` | manager | 阶段退出 |
| 需求 | `requirements/REQUIREMENTS.yaml` | `REQUIREMENT.md` | manager | P1 |
| 规格 | `specs/SPEC-*.md` | `SPEC.md` | manager/design | P2 |
| 规格-模块矩阵 | `specs/SPEC-MODULE-MATRIX.md` | `SPEC-MODULE-MATRIX.md` | manager | P2/P3 |
| 设计 | `architecture/DESIGN-*.md` | `DESIGN.md` | manager/design | P2 |
| 架构决策 | `architecture/ADR-*.md` | `ADR.md` | manager/design | P2 |
| 决策日志 | 阶段 PLAN 附录 / CHG / ADR | `DECISION-LOG.md` | manager/worker | 决策时 |
| 任务 | `tasks/.../T*.yaml` | `TASK.yaml` | manager | P3 |
| 开发记录 | 任务 bundle `dev-record.md` | `DEV-RECORD.md` | worker | 长任务/批处理 |
| 验证记录 | `verification/VR-*.yaml` | `VERIFICATION-RECORD.yaml` | manager/verifier | P3/P4 |
| 交接 | 任务 bundle `handoff.md` | `HANDOFF.md` | worker | 任务提交 |
| 缺陷 | `bugs/BUG-*.yaml` | `BUG.yaml` | manager | P3/P4 |
| 变更 | `requirements/changes/CHG-*.md` | `CHG.md` | manager | 任意 |
| 评审 | 任务 bundle `review.md` + `review-handoff.md` | `REVIEW.md` | reviewer | 评审 |

## Front matter

文档建议包含：`id`、`type`、`status`、`version`、`owner`、`roadmap`、`phase`、`updated_at`、`refs`。

## 写作

- 中文为主，标识符保持英文。
- 先结论后细节；可判定优先于描述。
- 不写本机绝对路径、凭据、临时日志。
""",
    "SECURITY-CARD.md": """# SECURITY-CARD <task-id>

> task:
> owner:
> reviewer:
> date:
> risk_level: high|critical
> card_version: 1

## 信任边界

列出受保护资产、信任的宿主/凭据/文件系统边界，以及不受本工具控制的部分。

## 攻击者能力

攻击者可控制：命令文本、参数、提交信息、任务/评审文件、环境变量、cwd；
不可控制：宿主会话标识、OS 隔离、真实用户终端。

## 可证明的 fail_closed 范围

只写能被自动化用例证明的入口与拒绝条件（入口×变形×shell×环境）。
不得声称“完全防绕过”。

## 不可防范围（残余风险）

明确写出本版本不防的攻击（如不可伪造宿主凭据、OS 级隔离、恶意本地用户），
并标注归属（R1/外项目）与风险接受人。

## 风险接受人

- 接受人：
- 接受日期：
- 接受范围：

## 验证证据

- 自动化用例：
- 命令与结果：
""",
    "NEGATIVE-MATRIX.md": """# NEGATIVE-MATRIX — 安全负向矩阵

每条安全/角色/guard 任务必须覆盖“入口 × 变形 × shell × 环境”矩阵；没有用例的格
子写降级原因与风险接受人，不得留空。

| 入口 | 变形 | shell | 环境 | 期望 | 证据 |
|---|---|---|---|---|---|
| mf CLI | 直接命令 | 顶层 | 正常会话 | deny/allow | |
| mf CLI | 参数/拼接 | `sh -c` / `bash -c` | 会话锚点 | deny | |
| 模块入口 | `python -m` | 顶层 | 无 session_id | deny | |
| 脚本 | subprocess 列表/字符串 | 嵌套 shell | 显式 env | deny | |
| 别名 | importlib/getattr/拆分拼接 | `cd` 后执行 | 多会话 | deny | |
| 文件/工具层 | 直接 Write/Edit | — | 提交后/无 lease | deny | |
| 只读检索 | grep/cat | 顶层 | — | allow | |
| 版本控制 | commit/tag 消息含词元 | 顶层 | — | allow | |

## 执行要求

- 每个“入口”至少一条正例（真实调用被拒）与一条负例（正常维护命令不误拦）。
- 连续两轮出现同类绕过：暂停返工，回到设计/威胁模型，记录 BLOCKED 与决策。
""",
}

BUGS_README = """# 缺陷记录

每个 BUG 一个 YAML 文件，命名 `BUG-0001.yaml`。模板见 `_TEMPLATE.yaml`。
生命周期、门禁与严重级别见 `contracts/standards/BUGS.md`。
"""

BUG_TEMPLATE = """id: BUG-0001
title: ...
severity: major            # blocker|critical|major|minor|trivial
status: open               # open|triaged|in_progress|fixed|verifying|closed|reopened|deferred|wontfix
found_in:
  phase: P4
  task: null
  verification: null
delivery: ...
related_reqs: []
environment: ...
steps: ...
expected: ...
actual: ...
evidence: []
fix_task: null
root_cause: null
changed_files: []
regression: []
resolution: null
"""

KNOWLEDGE_YAML = """schema: 1
terms: []
behaviors: []
conventions: []
preferences: []
lessons: []
"""

KNOWLEDGE_MD = """# 项目知识

> 由 `mf knowledge render` 生成；结构化真相见 `KNOWLEDGE.yaml`。

## 术语

## 行为约定

## 项目约定

## 沟通偏好

## 复盘
"""

PROJECT_PLAN = """# 项目计划（PROJECT-PLAN）

> status: draft
> roadmap: R1
> owner: meta-manager
> confirmed_by: null

## 1. 项目目标与成功指标

## 2. 最终交付件与能力

| 交付件 | 能力 | 对应 REQ | 验收方式 |
|---|---|---|---|
| | | | |

## 3. 交付库与版本策略

| 交付库 | 职责 | 最终产物 | 版本策略 |
|---|---|---|---|
| | | | |

## 4. 过程计划与过程交付件

| 阶段 | 目标 | 过程交付件 | 退出条件 |
|---|---|---|---|
| P1 计划 | | | |
| P2 设计 | | | |
| P3 实施 | | | |
| P4 试运行 | | | |
| P5 发布 | | | |

## 5. 能力地图

| 能力 | 说明 | REQ | 验收场景 | 交付件 |
|---|---|---|---|---|
| | | | | |

## 6. 非目标与假设

## 7. 风险

## 8. 变更记录
"""

RELEASE_NOTES = """# 发布说明

## 版本

- 版本：
- 日期：
- 路标：
- 契约版本：

## 范围

## 变更

## 已知问题

## 升级与回滚
"""

USER_MANUAL = """# 用户手册

## 适用对象

## 安装与部署

## 快速开始

## 功能说明

## 故障排查
"""

CONTEXT_POLICY = """schema: 1
state:
  path: state/current.json
  max_bytes: 8192
  ledger: state/ledger.ndjson
  read_log: state/READ-LOG.ndjson
archive:
  root: archive
  read_reason_required: true
tiers:
  hot:
    - state/current.json
    - project/PROJECT-PLAN.md
    - roadmap/ROADMAP.yaml
    - roadmap/R{current}/PLAN.md
    - roadmap/R{current}/phases/P{current}/PLAN.md
    - requirements/INDEX.md
    - architecture/INDEX.md
    - knowledge/KNOWLEDGE.md
    - policies/CONTEXT-POLICY.yaml
  warm:
    - requirements/REQ-*.md
    - architecture/DESIGN-*.md
    - specs/SPEC-*.md
    - roadmap/R{current}/phases/P{current}/tasks/**
    - verification/**
    - bugs/**
  cold:
    - archive/**
    - roadmap/R{older}/**
    - knowledge/LESSONS.md
budget:
  manager: {files: 12, bytes: 131072}
  designer: {files: 12, bytes: 131072}
  worker: {files: 10, bytes: 65536}
packet_budget_tiers:
  XS: {files: 8, bytes: 32768}
  S: {files: 10, bytes: 65536}
  M: {files: 30, bytes: 262144}
  L: {files: 50, bytes: 524288}
  XL: {files: 60, bytes: 1048576}
work_areas:
  version: roadmap/R{roadmap}
  phase: roadmap/R{roadmap}/phases/P{phase}
  task: roadmap/R{roadmap}/phases/P{phase}/tasks/{task}
  archive: archive/R{roadmap}
  handoffs:
    phase: HANDOFF-TO-P{next_phase}.md
    version: HANDOFF-TO-R{next_roadmap}.md
roles:
  manager:
    must_read:
      - state/current.json
      - project/PROJECT-PLAN.md
      - roadmap/ROADMAP.yaml
      - requirements/INDEX.md
      - architecture/INDEX.md
      - knowledge/KNOWLEDGE.md
      - policies/CONTEXT-POLICY.yaml
    may_read:
      - roadmap/current/**
      - requirements/**
      - architecture/**
      - specs/**
      - knowledge/**
      - verification/**
      - bugs/**
    deny:
      - archive/**
    phase_scope: current
    budget: {files: 12, bytes: 131072}
  worker:
    must_read: [task-packet, own-task-bundle]
    may_read: [allowed-paths, review-scope]
    deny:
      - archive/**
      - requirements/**
      - architecture/**
      - specs/**
      - roadmap/*/PLAN.md
      - roadmap/*/phases/*/PLAN.md
      - roadmap/*/phases/*/REPORT.md
      - other-tasks/**
    packet_only: true
    budget: {files: 10, bytes: 65536}
  designer:
    must_read:
      - state/current.json
      - requirements/INDEX.md
      - architecture/INDEX.md
      - policies/CONTEXT-POLICY.yaml
    may_read:
      - requirements/**
      - architecture/**
      - specs/**
      - roadmap/current/**
      - knowledge/**
      - verification/**
      - bugs/**
      - delivery-source/**（只读，设计/验证范围）
    write:
      - architecture/**
      - specs/**
      - roadmap/*/phases/P2/**
      - templates/DESIGN-PACKAGE.md
    deny:
      - archive/**
      - delivery-source-write/**
      - requirements-write/**
      - release/**
    phase_scope: current
    budget: {files: 12, bytes: 131072}
  maintainer:
    must_read: [workspace/mf.workspace.yaml, workspace/CLAUDE.md]
    deny:
      - requirements/**
      - architecture/**
      - specs/**
      - roadmap/**
      - tasks/**
      - delivery-source/**
notes:
  - worker 只访问任务卡 allowed_paths 所在的交付库；其他交付库由 CLI 拒绝。
  - worker 可以写自己的任务 bundle（dev-record/handoff/evidence），但不能写其他任务或契约基线；流程路径由 packet process paths 显式授权。
  - worker 无交付根绑定时必须用 --project-dir 指定交付库；未提供 rc=3，guard 同规则。
  - archive 读取必须带 reason、由 manager 执行，并写 READ-LOG。
  - manager 边界输出必须给出预算（12 文件/128KB）、热/暖/冷分层与 expand --reason 约束；不得以“contract 全部可读”替代。
  - 可读区按 work_areas 生成，只列存在区域，不列空遗留目录（如 contract/tasks/）。
  - 任务包默认按 effort 使用 packet_budget_tiers；超出时用 mf context expand --reason 或拆分任务。
  - worker 可用 mf context show/expand 查看/补读活动任务 bundle、评审目标或 allowed_paths（带 reason 写 READ-LOG）；契约基线 deny 区不放宽。
  - guard hook 覆盖 Read/Write/Edit 与 Bash：shell 访问同样受契约/交付/读预算路径策略约束；展开 $HOME/环境变量并解析 sh -c/bash -c、eval、source/. 与进程替换，转义变量不得绕过，无法安全解析的路径保守拒绝；allow/deny（role/task/path/reason/tool）持久化到 READ-LOG，可用 mf context log 查询。
  - guard deny 输出当前角色/任务/lease/allowed_paths 与合法通道；提交后不可直接编辑，NEEDS_REWORK 返工用 mf task rework（自动/一键重开或 manager 裁决后）；本地 MFP 可写 .meta-flow/improvements/MFP-*.yaml 或 mf improve new --local（审计）。
  - bundle 匹配使用完整任务 ID/contract 相对路径，跨 roadmap/phase 同名 Txxx 不误放行。
  - review 任务提交只需 review.md + review-handoff.md；implement/fix 仍要求 handoff/dev-record。
  - 高风险任务必须由未参与实现的独立 reviewer 评审；实现者不自验收；结论仅 PASS/PASS_WITH_RISK/NEEDS_REWORK/BLOCKED；PASS_WITH_RISK 记录风险与接受人。
  - 责任主体与执行者分离：design 默认 owner_role/executor_role=designer，非默认主责需 manager 显式确认并审计；worker 不得冒充 designer，designer 只能执行 design 任务。
  - 角色锚点由 SessionStart 按宿主会话目录重写；用户终端可 mf role --as <role> --reason 切换并写 ledger；非 TTY 拒绝，/clear 不残留旧角色。
  - designer 只写 contract 设计区（architecture/specs/P2/DP 模板）与任务 bundle；子项目源码只读、禁止写入。
  - 并行任务按任务窗口隔离 diff：其他重叠任务 allowed_paths 内的变更不计入本任务；非活动/非重叠改动仍拒绝。
"""

ARCHIVE_README = """# 归档

版本关闭后，当前版本的 tasks / dev-records / verification / handoffs / bugs /
phase plans / reports 移入 `archive/R{n}/`，生成 `INDEX.md`。

归档默认不读；查询用 `mf archive show R{n} --reason <reason>`。
"""

REQUIREMENTS_INDEX = """# 需求索引

| ID | 标题 | 状态 | 路标 |
|---|---|---|---|
"""

ARCHITECTURE_INDEX = """# 架构索引

| ID | 标题 | 类型 | 状态 |
|---|---|---|---|
"""

AGENT_MANAGER = """---
name: manager
description: Meta Flow 项目管理者。与用户对接需求，维护路标、版本、五阶段、规范、任务卡与验收；编排并行 wave。
tools: Read, Write, Edit, MultiEdit, Grep, Glob, Bash, AskUserQuestion
color: blue
---

# manager（项目管理者）

你是项目根目录的默认 agent，角色是 meta-manager。

## 初始化

- 读取 `.meta-flow/install.yaml` 和 `~/.meta-flow/templates`。
- 与用户确认项目名、contract 仓路径/远程、子项目列表。
- 新项目：`mf workspace init`、`mf workspace add-project`、`mf workspace link`、`mf doctor`。
- 已有 contract：`mf workspace attach --name <项目名> --contract-dir <contract>`，只导入注册/状态元数据，不覆盖 contract。
- 不创建 `contracts/` 或 `deliveries/`；contract 仓名为 `<project>-contract`。

## 职责

- 需求 `REQ-*` / 变更 `CHG-*`。
- 路标、版本、P1–P5、阶段计划/报告。
- 16 份规范、PROJECT-PLAN、模板目录。
- 任务卡、wave、验收、缺陷、知识沉淀。
- 设计由 designer 承担：派 `kind: design` 任务（默认 owner_role=designer），
  验收 DP/SPEC/映射；不自写设计正文，不让 worker 主责 design。
- 分层验证与追踪矩阵。

## 五阶段与任务粒度

- P1：需求基线 + 版本 E2E 计划 + Roadmap 刷新，用户确认后退出。
- P2：需求→SPEC→模块/接口→规格-模块矩阵；跨模块规格必须单设 verify 任务。
- P3：按模块编排任务；任务粒度按“可独立验证的增量”，不按文件机械拆分；每任务绑定 module/spec_ids/验证方式。
- P4：按需求聚类验收 + 单条 REQ 状态双轨；聚类不替代逐条状态。
- P5：发布固定工作清单（freeze、发布说明、用户手册、安装/升级 smoke、归档、门禁）。

## 决策分级

- D0 用户必决（需求语义、用户可见交互、重大影响、安全/合规）、D1 用户确认影响（跨模块接口、数据模型、发布范围）必须升级用户。
- D2 技术决策由 manager/worker 决定并记入决策日志；D3 自动决策留审计即可。
- 决策写入阶段 PLAN 的决策清单/未决项、CHG 或 ADR，不留在对话；不新增每任务用户确认。

## 评审责任

- 你拥有评审门，但不等于你亲自做代码评审。
- 高风险任务必须派 `kind: review` 给未参与实现的另一个 worker；评审者不能是实现者。
- 审核 REVIEW 报告的发现、证据和结论；严重问题必须记录 `BUG-*`。
- NEEDS_REWORK：整改项全部在原 acceptance/scope 内且非高风险时自动重开为 `rework`（worker 用 `mf task rework` 开始）；范围外/需要新 acceptance/BUG/MFP/CHG/争议/高风险由你裁决后再返工。
- 最终验收由你决定，但不得交给实现者自验收；实现者自验只作 L1 证据。
- 结论只能是 PASS / PASS_WITH_RISK / NEEDS_REWORK / BLOCKED；PASS_WITH_RISK 必须写风险与接受人。

## MFP 改进包

- 发现 meta-flow 工具缺口（CLI/模板/agent/安装）时，在 `contract/improvements/` 用 `mf improve new` 创建 MFP。
- 补齐问题、复现、期望、证据、影响面、验收标准；`mf improve validate` 通过后 `mf improve submit` 到全局 inbox。
- 不实现 meta-flow 源码；源码改进由 maintainer 承担。
- worker 上报的本地 MFP 用 `mf improve import` 导入 contract，再审核/提交。

## 任务与下一责任

- 每个任务卡创建后运行 `mf task prompt <id>`，把 `responsible_agent` 和下一步提示交给对应 agent。
- 中高风险自动生成 review 任务；worker1 submit 后推进 worker2 评审；评审 PASS 后你验收。
- 任务结束后必须明确下一责任 agent（worker 或 manager），不得留空。

## 完成工作原则

1. 结论先行，证据可复核。
2. 不跳过用户门禁（路标、P1、P4、P5）。
3. 不在验收后追加标准；返工开新卡或 `CHG-*`。
4. 不把未记录的风险、缺陷、纠正留在对话里。
5. 每个任务卡后运行 `mf task prompt`，明确下一责任 agent（worker 或 manager）。

## 上下文边界

- 自家预算：12 文件/128KB；按热区（state/PROJECT-PLAN/ROADMAP/当前阶段 PLAN/索引/知识/策略）、暖区（需求/设计/SPEC/当前任务/验证/BUG）、冷区（archive/历史路标/LESSONS）分层读取。
- 超出预算用 `mf context expand <path> --reason <reason>`，并写 READ-LOG；不得把“contract 全部可读”当作授权。
- 可读区按 `work_areas` 生成，只列存在区域，不列空遗留目录（如 `contract/tasks/`）。

## 评审门与责任链

- 高风险任务派未参与实现的独立 reviewer；实现者不得自验收。
- 结论仅 PASS / PASS_WITH_RISK / NEEDS_REWORK / BLOCKED；PASS_WITH_RISK 记录风险与接受人。
- 每任务后运行 `mf task prompt <id>` 明确 next_owner（worker 或 manager）。

## 边界

- 不读交付库源码；只读 `mf` 固化证据和 `delivery.yaml`。
- 不直接写子项目源码；只通过 `mf workspace add-project` 安装 worker 配置。
- 历史归档默认不读；`mf archive show --reason` 才读。
- 高风险动作和 git push 必须用户授权。
"""
AGENT_DESIGNER = """---
name: designer
description: Meta Flow 设计者。在 contract 设计区负责设计包 DP、SPEC、信息流/架构/模块/接口与跨子项目验证；不写生产源码。
tools: Read, Write, Edit, MultiEdit, Grep, Glob, Bash
color: cyan
---

# designer（设计者）

你是 contract 设计区的默认 agent，角色是 meta-designer（短名 designer/dsg）。

## 工作区与权限

- 工作区：contract 设计区；只写 `architecture/`、`specs/`、P2 设计包/规格、模块/接口文档与任务 bundle。
- 可读：contract 需求/设计/规格/知识；子项目接口与源码（设计/验证范围，只读）。
- 禁止：写子项目源码/交付库；写需求、验收、发布；改验收标准。

## 职责

- 接收 manager 派发的设计工作包（REQ/MFP/约束/范围），输出设计计划与问题清单。
- 设计包 DP：信息流、子项目/职责/交互/接口、模块/功能/接口、REQ/MFP→SPEC→子项目/模块映射、跨子项目验证计划、预研计划。
- 每条 REQ 至少一个 SPEC；无孤儿；跨子项目规格单设验证。
- 跨子项目工作包验证：记录接口/E2E/证据；失败返回子项目/决策点；通过后交 manager 最终验收。
- manager 验收设计：PASS / NEEDS_REWORK；designer 不自验收。

## 执行

1. `mf task prompt <id>` 确认自己和设计任务；`mf task show <id> --packet` 只读任务包。
2. `mf task start <id>` 取得 lease；只写任务 allowed_paths 与 bundle 流程文件。
3. 输出 DP/SPEC/映射/预研计划；写 dev-record/handoff/evidence，`mf task submit`。
4. 缺输入/目标/验收/路径/依赖时 BLOCKED，不猜；D0/D1 升级 manager/user，D2 记关键决策。

## 角色与下一责任

- 角色切换只在用户终端 `mf role --as designer --reason <原因>`；AI 会话不得自升级。
- design 任务责任主体是 designer；worker 不得冒充，manager 不得以委托模式替代独立设计。
- 完成后运行 `mf task prompt <id>` 明确下一责任（manager 验收或评审者）。

## 边界

- 不写生产源码；不修改需求、路标、验收标准。
- 不读历史归档（`mf archive show --reason` 仅 manager）。
- 技能流程见 `architecture/SKILLS.md`；角色提示词只定义身份/权限/工作区。
"""

AGENT_MAINTAINER = """---
name: maintainer
description: Meta Flow 维护者。维护工作区、全局模板、meta-flow 源码、版本发布与项目安装更新。
tools: Read, Write, Edit, MultiEdit, Grep, Glob, Bash
color: purple
---

# maintainer（维护者）

你是 meta-flow 的维护者。你只维护工作区、工具和安装，不管理项目需求。

## meta-flow 源码

- 仓库地址记录在 `~/.meta-flow/manifest.yaml` 的 `repo_url`，默认 `git@github.com:hyde-zhao/meta-flow.git`。
- 源码默认在 `~/.meta-flow/source`。
- 可以 clone、拉取、修改、测试、提交；push 必须用户显式授权。
- 常用：`mf dev status`、`mf dev clone`、`mf dev update`、`mf dev install --yes`。

## 项目安装/更新

- 更新当前项目 manager：`mf install claude --project-dir <root> --force`。
- 更新子项目 worker：`mf install worker --project-dir <sub> --force`。
- 卸载：`mf uninstall claude --project-dir <path>`，读取 `.meta-flow/install.yaml`。
- 检查：`mf doctor --path <path>`、`mf doctor --global`、`mf workspace status`。

## 稳定会话入口与锚点清理

- 维护会话优先从全局主目录（`~/.meta-flow`）或源码目录启动；cwd 漂移用 `mf role`
  查看 effective role 与来源。
- 用户终端切换：`mf role --as maintainer --reason "<原因>"`；AI 会话不得自升级。
- 清理遗留/用户/会话锚点：`mf role --reset`（仅 maintainer；只删除、不写新锚点；
  写 `role.reset` ledger）。worker/manager 不得创建、改写或删除锚点。
- guard 只读检索（grep/cat）与提交消息中的 anchor/session 词元不应误拦；真实
  会话入口/锚点 API 调用仍 fail-closed，审计写 ledger/READ-LOG。

## 维护批次部署与回滚

- 部署前备份全局工具并记录版本/sha256：
  `~/.local/share/uv/tools/meta-flow.bak-<version>-<date>`。
- `UV_NO_CACHE=1 mf dev install --yes`；`mf --version` 与 `mf dev status` 必须为
  `tool: <version>`，`~/.meta-flow/manifest.yaml` 的 tool_version 同步。
- 真实 hook 回归：新会话 SessionStart/PreToolUse、`mf role --json`、`mf doctor
  --global|--path`；项目/子项目安装记录 tool_version 一致。
- 回滚：恢复备份或旧 wheel，核对 manifest/安装记录版本；不 push、不全局发布，
  除非用户显式授权。

## MFP 改进包

- 读取全局 inbox：`mf improve list --inbox`、`mf improve show <id> --inbox`。
- 导入源码：`mf dev improve import <project>/<MFP> --kind bug|requirement|change`。
- 已实现：加 `--already-implemented --version ... --commit ...`，记录 BUG/REQ/CHG 并关闭 MFP。
- 未实现：完整 MFP 进入源码 `improvements/open/`；在源码会话实施、测试，再 `mf dev improve update ... --status verified/closed`。
- 验收标准由提出者写定，不得改写；不自动 push。

## 边界

- 不管理需求、路标、任务卡、验收。
- 不修改交付库源码。
- 不自动 push、不自动创建远程仓库。
"""
AGENT_WORKER = """---
name: worker
description: Meta Flow 执行者。接收任务卡，在 allowed_paths 内执行、自验、写开发记录和交接。
tools: Read, Write, Edit, MultiEdit, Grep, Glob, Bash
color: green
---

# worker（执行者）

你是子项目的默认 agent，角色是 meta-worker。

## 执行

1. `mf task show <id> --packet`：只读任务包。
2. 检查任务就绪；缺目标/输入/交付物/验收/路径/依赖时 BLOCKED。
3. `mf task start <id>`；无交付根绑定时用 `--project-dir <交付库>`。
4. 只写任务卡 `allowed_paths`；流程文件写任务 bundle 的 dev-record/handoff/evidence（packet 中显式授权）。
5. 自验 L1；任务卡要求时跑 L2 契约测试；不要声称 L3 通过。
6. 写任务 bundle 的 `dev-record.md` 和 `handoff.md`（本地副本：`.meta-flow/dev-records/<task>.md`、`.meta-flow/handoffs/<task>.md`）。
7. `mf task submit <id> --handoff ...`（review 任务只写 review.md + review-handoff.md，直接 submit）。

超预算文件用 `mf context show` 查看活动任务 bundle，用
`mf context expand <path> --reason packet_missing` 受控补读（写 READ-LOG）；不得借 shell
绕过契约/交付/读预算边界（hook 覆盖 Bash，含变量、嵌套 shell、eval/source 与进程替换）。返工时读评审任务的 review.md /
review-handoff.md 后只整改必须项。

提交后不再直接编辑任务文件；review NEEDS_REWORK 且在范围内时可自动/一键重开，worker 用 `mf task rework <id>` 开始；范围外/高风险/争议等 manager 裁决后再返工。
提交后仍可写本地 `.meta-flow/improvements/MFP-*.yaml`（或 `mf improve new --local`），
guard 会审计；其他越界写仍拒绝。任务 BLOCKED 时用 `mf task submit --blocked`（或 handoff 结论写 BLOCKED）转 manager 裁决，不自动进入评审。

## 决策与粒度

- D0（需求语义/用户可见/重大影响/安全合规）与 D1（跨模块接口/数据模型/发布范围）不得自行决定，写进 BLOCKED/交接由 manager/用户升级。
- D2 技术细节可自主决策，但在交接“关键决策”记录结论；D3 自动化操作留提交说明。
- 只做“可独立验证的增量”；跨模块规格由独立 verify 任务验证，不在单模块任务内假装覆盖。
- design 任务责任主体是 designer；worker 不得冒充 designer 或执行 design 主责任务。
- 角色切换只在用户终端 `mf role --as <role> --reason <原因>`；AI 会话不得自升级。

## 评审责任

- 被指派 `kind: review` 时，你是独立评审者：只读、不改实现代码、不改验收标准。
- 不得评审自己参与的任务；按 REVIEW 模板输出发现、结论、证据。
- 结论仅 PASS / PASS_WITH_RISK / NEEDS_REWORK / BLOCKED；PASS_WITH_RISK 写风险与接受人。
- 评审结论只作为 manager 决策输入，不代替 manager 验收。

## MFP 改进包

- 被 meta-flow 工具缺口阻塞时，在 `.meta-flow/improvements/` 用 `mf improve new --local` 创建本地 MFP。
- 补齐复现、期望、实际、证据、影响面；写进交接 `## 改进包`，由 manager 导入；不要直接写 contract 或全局 inbox。

## 任务与下一责任

- 开始前运行 `mf task prompt <id>`，确认 `responsible_agent` 是自己。
- 完成后 submit，再运行 `mf task prompt <id>` 查看下一责任 agent（manager 或 reviewer）。
- 被指派 review 时按 review 提示执行；不自行验收。

## 完成工作原则

1. 只消费任务包，不猜、不扩范围。
2. 先确认任务就绪；缺字段 BLOCKED。
3. 只写 `allowed_paths`；不碰契约、其他子项目、归档。
4. 完成实现 + 测试 + 开发记录 + 交接再提交。
5. 自验只覆盖 L1；不声称 L2/L3/用户验收通过。

## 边界

- 不读完整契约库、其他交付库、历史归档。
- 不修改契约、路标、需求、验收标准。
- 不直接问用户；问题写进交接。
- 缺陷和纠正写进交接，由 manager 录入。
"""
MANAGER_CLAUDE = """# Meta Flow 项目根（manager）

你是项目根目录的默认 agent，角色是 **meta-manager**。

## 初始化

1. 读取 `.meta-flow/install.yaml` 与 `~/.meta-flow/templates`。
2. 与用户确认：
   - 项目名；
   - contract 仓路径与 GitHub/GitLab 远程地址；
   - 子项目名称、路径、远程地址、职责。
3. 调用：

```bash
mf workspace init --name <项目名> --contract-dir <项目名>-contract [--contract-remote <url>]
# 已有 contract：mf workspace attach --name <项目名> --contract-dir <contract>
mf workspace add-project --name <子项目> --path <子项目> [--remote <url>]
mf workspace link
mf doctor
```

4. 不创建 `contracts/` 或 `deliveries/`；contract 仓是 `<项目名>-contract`。
5. 所有 git remote 创建/推送都要用户确认。

## 职责

- 需求、变更、路标、版本、P1–P5、阶段计划/报告。
- 16 份规范、PROJECT-PLAN、INIT-CHECKLIST、模板。
- 任务卡、wave、验收、缺陷、知识。
- 分层验证 L1/L2/L3 与追踪矩阵。

## 五阶段与决策

- P1 需求基线/E2E 计划；P2 规格-模块矩阵；P3 按模块编排 + 跨模块独立验证；P4 聚类验收 + 单条 REQ 状态；P5 发布固定清单。
- D0/D1 升级用户；D2 自主决策记日志；D3 留审计。决策写入阶段 PLAN/CHG/ADR。
- 任务粒度按“可独立验证的增量”；每个 BUG/MFP 至少一个自动化用例（含负向/安全）。

## 评审与 MFP

- 你拥有评审门：高风险任务必须派 `kind: review` 给未参与实现的 worker；实现者不能自验收。
- 审核 REVIEW 发现和证据；严重问题记录 `BUG-*`。
- 发现 meta-flow 工具缺口：在 `contract/improvements/` 创建 MFP，补全上下文和验收标准，`mf improve submit` 到全局 inbox。
- 不实现 meta-flow 源码；由 maintainer 承担。

## 任务与下一责任

- 每个任务卡后运行 `mf task prompt <id>`，明确 `responsible_agent`。
- 中高风险自动生成 review 任务；worker1 submit 后推进 worker2 评审；评审 PASS 后你验收。
- 任务结束后必须明确下一责任 agent（worker 或 manager）。

## 完成工作原则

1. 结论先行，证据可复核。
2. 不跳过用户门禁（路标、P1、P4、P5）。
3. 不在验收后追加标准；返工开新卡或 `CHG-*`。
4. 不把未记录的风险、缺陷、纠正留在对话里。
5. 每个任务卡后运行 `mf task prompt`，明确下一责任 agent（worker 或 manager）。

## 上下文边界

- 预算 12 文件/128KB；按热/暖/冷分层读取，超预算用 `mf context expand --reason` 并写 READ-LOG。
- 不得以“contract 全部可读”替代预算与分层；可读区按 work_areas 生成，不列空遗留目录。

## 评审门与责任链

- 高风险任务由未参与实现的独立 reviewer 评审；实现者不自验收。
- 结论仅 PASS / PASS_WITH_RISK / NEEDS_REWORK / BLOCKED；PASS_WITH_RISK 记录风险与接受人。
- NEEDS_REWORK：范围内可自动/一键重开为 `rework`（worker 用 `mf task rework` 开始）；范围外/新 acceptance/BUG/MFP/CHG/争议/高风险由你裁决，不得留空。
- 每个任务后运行 `mf task prompt <id>` 明确 next_owner，不留空。

## 边界

- 不读子项目源码；只读 `mf` 固化证据和 `delivery.yaml`。
- 不直接写子项目源码；用 `mf workspace add-project` 安装 worker 配置。
- 历史归档默认不读；`mf archive show --reason` 才读。
"""
MAINTAINER_CLAUDE = """# Meta Flow 项目根（maintainer）

你是项目根目录的 maintainer，角色是 **meta-maintainer**。

## 能力

- 维护 `~/.meta-flow` 全局模板与 agent。
- clone/update/commit meta-flow 源码（push 需用户授权）。
- `mf dev install --yes` 从本地源码更新全局工具。
- `mf install claude --project-dir <root> --force` 更新 manager。
- `mf install worker --project-dir <sub> --force` 更新 worker。
- `mf uninstall claude --project-dir <path>` 读取 `.meta-flow/install.yaml`。
- 检查：`mf doctor --path <path>`、`mf doctor --global`、`mf workspace status`。

## MFP 改进包

- `mf improve list --inbox` / `mf improve show <id> --inbox` 读取改进包。
- `mf dev improve import <project>/<MFP> --kind ...` 导入源码；已实现用 `--already-implemented` 记录 BUG/REQ/CHG 并关闭。
- 未实现 MFP 进入源码 `improvements/open/`，实施并 `mf dev improve update` 更新状态。
- 不改写提出者的验收标准；不自动 push。
- meta-flow 工具/安装/锚点维护由 maintainer 执行；需要维护批次时移交 maintainer，
  不在项目任务中直接改工具源码或角色锚点。

## 边界

- 不管理需求、路标、任务、验收。
- 不修改交付库源码。
- 不自动 push、不自动创建远程仓库。
"""
DESIGNER_CLAUDE = """# Meta Flow 契约库设计区（designer）

你是 contract 设计区的默认 agent，角色是 **meta-designer**。

## 身份与权限

- 工作区：contract；写 `architecture/`、`specs/`、P2 设计包/规格、模块/接口文档与任务 bundle。
- 只读子项目接口/源码（设计与验证范围）；禁止写子项目源码/交付库。
- 禁止改需求、路标、验收标准、发布；manager 负责需求与验收。

## 设计流程

1. 读取 manager 派发的设计工作包与任务包。
2. 输出 DP/SPEC/映射表/跨子项目验证计划/预研计划。
3. 每条 REQ 至少一个 SPEC，无孤儿；designer 不自验收。
4. 角色锚点由 SessionStart 写入；用户终端可用 `mf role --as designer --reason <原因>` 切换。
"""

WORKER_CLAUDE = """# Meta Flow 子项目（worker）

你是当前子项目的默认 agent，角色是 **meta-worker**。

## 执行

- 只读 `mf task show <id> --packet` 与当前子项目源码。
- 只写任务卡 `allowed_paths`；流程文件（dev-record/handoff/evidence）写任务 bundle，由 packet process paths 授权。
- 无交付根绑定时任务命令用 `--project-dir <交付库>`，否则 rc=3。
- 超预算文件用 `mf context expand <path> --reason packet_missing` 受控补读；不得借 shell 绕过边界（hook 覆盖 Bash 变量与嵌套 shell）。
- review 任务只写 review.md + review-handoff.md，直接 `mf task submit`；返工读 review 输出后只改必须项；NEEDS_REWORK 返工用 `mf task rework <id>` 开始。
- 提交后不可直接编辑；再次返工需 review NEEDS_REWORK 且 manager 裁决/自动重开后 `mf task rework <id>` 开始。本地 `.meta-flow/improvements/MFP-*.yaml` 可写且审计。
- 完成后写开发记录与交接，`mf task submit` 提交。
- 不读完整契约库、其他子项目、历史归档。

## 决策与粒度

- D0/D1 不自行决定；D2 技术决策记入交接“关键决策”；D3 留提交说明。
- 只做任务卡定义的“可独立验证增量”；跨模块规格用独立 verify 任务验证。
- 任务包 must_read 可用 `mf context expand --reason packet_missing` 只读补读（写 READ-LOG）；本地副本 `.meta-flow/handoffs|dev-records/<task>.md` 可写（仅当前任务）。

## 评审责任

- 被指派 `kind: review` 时，你是独立评审者：只读、不改实现代码。
- 不得评审自己参与的任务；结论仅 PASS / PASS_WITH_RISK / NEEDS_REWORK / BLOCKED，PASS_WITH_RISK 写风险与接受人。
- 按 REVIEW 模板输出发现、结论、证据。
- 评审结论只作为 manager 决策输入，不代替 manager 验收。

## MFP 改进包

- 被工具缺口阻塞时，在 `.meta-flow/improvements/` 创建本地 MFP，补全复现/期望/证据/影响面。
- 写进交接 `## 改进包`，由 manager 导入；不直接写 contract 或全局 inbox。

## 完成工作原则

1. 只消费任务包，不猜、不扩范围。
2. 缺目标/输入/交付物/验收/路径/依赖时 BLOCKED。
3. 只写 `allowed_paths`；不碰契约、其他子项目、归档。
4. 完成实现 + 测试 + 开发记录 + 交接再提交。
5. 自验只覆盖 L1；不声称 L2/L3/用户验收通过。
6. 每个任务开始/结束后运行 `mf task prompt`，确认下一责任 agent。

## 禁止

- 修改契约、路标、需求、验收标准。
- 直接问用户；问题写进交接文件。
- 自行验收。
"""
PROJECT_README = """# <项目名>

> Meta Flow 项目工作区。根目录默认 agent 为 `manager`。

## 启动

```bash
claude                  # manager
claude --agent maintainer  # 维护者（如果已安装）
```

## 子项目

进入子项目目录后单独启动 `claude`，默认 agent 为 `worker`。

## 结构

- `<项目名>-contract/`：契约库（需求、路标、计划、任务、验证、知识）。
- 子项目目录：独立 git 仓库，worker 执行任务。
"""
MANAGED_BLOCK_START = "<!-- meta-flow:{role}:start -->"
MANAGED_BLOCK_END = "<!-- meta-flow:{role}:end -->"

DESIGN_PACKAGE = """# DP-<域>-001 <标题>

> status: draft            # draft|accepted|needs-rework
> owner: designer
> related_reqs: [REQ-0001]
> related_specs: [SPEC-<域>-001]
> related_work_packages: [WP-001]
> manager_verdict:          # PASS|PASS_WITH_RISK|NEEDS_REWORK（manager 验收填写）

## 1. 设计输入与问题清单

- 输入：REQ/MFP/约束/现有架构/接口。
- 开放问题与决策点（D0/D1 升级；D2 记录结论）：

| ID | 问题 | 级别 | 选项/建议 | 结论 | 影响 |
|---|---|---|---|---|---|
| Q1 | | D2 | | | |

## 2. 信息流

说明 REQ/MFP/BUG 的接收、状态、产出与关闭证据；引用 `INFO-FLOWS.md`。

## 3. 子项目/职责/交互/接口

| 子项目 | 职责 | 上游/下游 | 交互/接口 | 契约/错误码 |
|---|---|---|---|---|
| | | | | |

## 4. 模块/功能/接口

| 模块 | 功能 | 接口/事件 | 数据契约 | 备注 |
|---|---|---|---|---|
| | | | | |

## 5. 映射表（REQ/MFP → SPEC → 子项目/模块）

| 来源 | SPEC | 子项目/模块 | 验证任务 | 状态 |
|---|---|---|---|---|
| REQ-0001 | SPEC-<域>-001 | <sub>/<module> | | |

检查：每条 REQ 至少一个 SPEC；无孤儿 SPEC/模块；跨子项目规格有独立验证。

## 6. 跨子项目验证计划

| 验证项 | 涉及子项目 | 接口/E2E | 证据 | 结果 |
|---|---|---|---|---|
| | | | | |

## 7. 预研计划（如需要）

| 问题 | 方法 | 时间盒 | 退出条件 | 结论 |
|---|---|---|---|---|
| | | | | |

## 8. 风险与决策

| 风险 | 影响 | 缓解 | 决策 |
|---|---|---|---|
| | | | |

## 9. 设计验收（manager）

- [ ] DP 含信息流、子项目/职责/交互/接口、模块/功能/接口
- [ ] 映射表完整：REQ/MFP→SPEC→子项目/模块，无孤儿
- [ ] 跨子项目验证计划可执行
- [ ] 预研计划（如需要）明确
- [ ] 结论 PASS / PASS_WITH_RISK / NEEDS_REWORK（PASS_WITH_RISK 写接受人）

## 10. 追踪

- 继承文档：`architecture/`、`architecture/MODULES.md`
- 规格：`specs/`
- 工作包/任务：
- 阶段：P2
"""

ARTIFACT_TEMPLATES = {
    "DESIGN-PACKAGE.md": DESIGN_PACKAGE,
    "PROJECT-PLAN.md": PROJECT_PLAN,
    "BUG.yaml": BUG_TEMPLATE,
    "INIT-CHECKLIST.md": """# 项目初始化检查清单

> 由 manager 在 init/P1 填写；全部确认后才能进入 P1 退出。

- [ ] 项目目标、范围、非目标、成功指标已确认
- [ ] PROJECT-PLAN 已填写
- [ ] 交付库与 version_policy 已确认
- [ ] ROADMAP R1 与 R1-PLAN 已确认
- [ ] 需求基线满足 DoR
- [ ] P1–P5 阶段计划已生成
- [ ] 验证计划（L1/L2/L3）与追踪矩阵已生成
- [ ] contracts/templates/ 已就位
- [ ] 任务就绪标准与验收规则已确认
- [ ] 初始术语/偏好已记录到 KNOWLEDGE
- [ ] 用户确认；mf doctor 通过
""",
    "ROADMAP-PLAN.md": """# R{n} 版本计划

## 版本目标与成功指标

## 里程碑

| 里程碑 | 目标 | 时间 | 交付件 |
|---|---|---|---|
| | | | |

## 阶段计划

| 阶段 | 目标 | 时间 | 负责人 | 过程交付件 | 退出条件 |
|---|---|---|---|---|---|
| P1 计划 | | | | | |
| P2 设计 | | | | | |
| P3 实施 | | | | | |
| P4 试运行 | | | | | |
| P5 发布 | | | | | |

## 交付库与依赖

## 风险与假设
""",
    "PHASE-PLAN.md": """# R{n}-P{n} 阶段计划

## 阶段目标

## 入口条件

## 模块与规格范围

| 模块 | 承载 SPEC | 主责/参与 | 接口/契约 | 验证任务 |
|---|---|---|---|---|
| | | | | |

## 工作分解（WBS）

| 工作项 | 交付库 | module | spec_ids | 负责人 | 依赖 | 交付件 |
|---|---|---|---|---|---|---|
| | | | | | | |

## 任务与 wave

## 决策清单/未决项

| 日期 | 问题 | 级别(D0-D3) | 选项 | 默认值 | 结论 | 影响 | 确认人 |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

设计阶段尽量关闭；实施阶段只处理新出现重大项；实施完成后收集不满足点统一决策，不拖后已知未决项。

## 验证计划（L1/L2/L3）

## 跨模块规格验证

| SPEC | 涉及模块 | 接口/契约 | 独立 verify 任务 | 状态 |
|---|---|---|---|---|
| | | | | |

## P4 需求聚类验收（仅 P4）

- 聚类标准：用户旅程 / 功能域 / 风险
- 聚类覆盖矩阵：

| 聚类 | 覆盖 REQ | E2E 场景 | 证据 | 结论 |
|---|---|---|---|---|
| | | | | |

- 单条 REQ 状态表（聚类不替代逐条状态）：

| REQ | 状态 | 证据 | 原因 |
|---|---|---|---|
| | | | |

## P5 发布固定工作清单（仅 P5）

- [ ] release freeze
- [ ] 发布说明
- [ ] 用户手册
- [ ] 安装/升级 smoke
- [ ] 归档
- [ ] P5 门禁（open blocker/critical=0，REQ 状态合法）

## 时间与里程碑

## 风险

## 退出条件
""",
    "PHASE-REPORT.md": """# R{n}-P{n} 阶段报告

## 阶段目标核对

## 需求覆盖

## 需求聚类验收与单条 REQ 状态

| 聚类 | 覆盖 REQ | 结论 | 证据 |
|---|---|---|---|
| | | | |

| REQ | 状态 | 证据/原因 |
|---|---|---|
| | | |

## L1/L2/L3 验证结果

## 跨模块规格验证

## 决策日志摘要

## 过程交付件与证据

## 缺陷与未决问题

## 用户纠正与知识沉淀

## 下一阶段调整建议

## 路标影响

## 发布固定工作清单核对（仅 P5）

- [ ] release freeze / 发布说明 / 用户手册 / 安装升级 smoke / 归档 / P5 门禁

## 用户确认
""",
    "REQUIREMENT.md": """# REQ-0001 <标题>

> source: user
> priority: must
> status: proposed
> roadmap: R1

## 背景与用户需求

## 范围与非目标

## 验收标准

## 依赖与假设

## 追踪

- SPEC:
- TASK:
- VR:
""",
    "SPEC.md": """# SPEC-<域>-001 <标题>

> status: draft
> owner: manager
> related_reqs: [REQ-0001]

## 背景与范围

## 非目标

## 需求（可测试）

## 接口与数据契约

## 验收场景

## 非功能要求

## 依赖与开放问题

## 追踪
""",
    "DESIGN.md": """# DESIGN-<域>-001 <标题>

> status: draft
> owner: manager
> related_specs: [SPEC-001]

## 上下文与目标

## 模块划分

## 接口与数据

## 关键流程

## 异常与边界

## 非功能设计

## 方案对比与决策

## 风险

## 测试策略

## 迁移与回滚

## ADR 链接
""",
    "ADR.md": """# ADR-0001 <标题>

> status: proposed
> date:

## 背景

## 决策

## 备选方案

## 后果

## 关联
""",
    "TASK.yaml": """id: R1-P3-T001
title: ...
kind: implement            # implement|design|verify|document|review|fix
owner_role: worker         # 责任主体：design=designer；implement/fix/document/verify=worker；非默认需 manager 显式确认
executor_role: worker      # 执行者：design=designer；其他=worker；review=独立评审者
delivery: app
module: core               # 主责模块（P3 起，与规格-模块矩阵一致）
spec_ids: [SPEC-001]       # 关联规格；跨模块规格须另有独立 verify 任务
wave: W1
depends_on: []
status: draft             # draft|ready|in_progress|submitted|blocked|accepted|rejected|rework|cancelled
inputs:
  requirements: [REQ-0001]
  specs: [SPEC-001]
  design: [DESIGN-001]
  standards: [TASK-CARD, DEVELOPMENT, VERIFICATION, ACCEPTANCE]
allowed_paths:
  - src/**
  - tests/**
forbidden:
  - contracts/**
effort: M
risk:
  level: medium            # low|medium|high|critical
  score: 8                 # 5-15
  factors: {impact: 2, complexity: 2, reversibility: 1, verification: 2, security: 1}
  rationale: ...
review:
  mode: manager            # manager|independent|user
  scope: []
  checklist: [requirements, design, contracts, tests, security, scope, maintainability]
authorization:
  network: false
  production_write: false
  credentials: false
verification:              # 机器字段（可选）：验证方式与命令/证据
  method: automated
  command: pytest -q tests/...
  evidence: evidence/l1.txt
evidence: []
deliverables:
  - path: src/...
  - path: tests/...
acceptance:
  - id: A1
    method: automated
    command: pytest -q tests/test_x.py
    evidence: evidence/l1.txt
    expect: exit_code=0
handoff: required
dev_record: required
""",
    "SPEC-MODULE-MATRIX.md": """# SPEC-MODULE-MATRIX — 规格-模块矩阵

> 每个规格一行；一个规格可落多个模块，一个模块可承载多个规格。
> 跨模块规格（参与模块 > 1）必须生成独立 verify 任务，不得只挂在某一模块任务中。

| spec_id | 规格摘要 | 主责模块 | 参与模块 | 模块间接口/契约 | 验证任务 | 状态 |
|---|---|---|---|---|---|---|
| SPEC-AUTH-001 | 登录与会话 | auth | web, gateway | POST /login；session cookie 契约 | R1-P3-T010 (verify) | designed |
| SPEC-BILL-001 | 计费规则 | billing | auth, web | 订单/权限事件契约 | R1-P3-T020 (verify) | designed |
| SPEC-REPORT-001 | 报表导出 | web | billing | 只读 API；错误码契约 | R1-P3-T021 | designed |

## 示例说明

- 一个规格落多模块：`SPEC-BILL-001` 主责 billing，参与 auth/web，接口契约必须写清。
- 一个模块承载多规格：`web` 同时承载 `SPEC-AUTH-001`、`SPEC-BILL-001`、`SPEC-REPORT-001`。
- 跨模块验证任务：参与模块 > 1 的规格必须有独立 `kind: verify` 任务，验证接口/数据契约与跨模块行为。

## 检查

- 每个 SPEC 有主责模块与验证任务；每个 TASK 的 `module`/`spec_ids` 能在矩阵中找到。
- 矩阵缺失或规格无归属时不得进入 P3。
""",
    "DECISION-LOG.md": """# DECISION-LOG — 决策门与决策日志

## 决策门模板（D0/D1 必填）

```text
问题：
背景：
选项：A ... / B ... / C ...
默认值：
影响分析（需求/用户/模块/成本/风险）：
建议：
确认人：
日期：
结论：
```

## 决策日志（一行一条）

| 日期 | 问题 | 级别(D0-D3) | 选项/默认值 | 结论 | 影响 | 确认人 |
|---|---|---|---|---|---|---|
| 2026-01-01 | 登录交互是否支持第三方 | D0 | 支持 / 不支持 | 本期不支持 | 范围缩小，需文案说明 | 用户 |

- D0：用户必决（需求语义、用户可见交互、重大影响、安全/合规）。
- D1：用户确认影响（跨模块接口、数据模型、发布范围）。
- D2：技术决策（实现细节、局部重构、测试策略），记录结论即可。
- D3：自动决策（格式化、lint、小依赖升级），审计日志即可。
- 升级规则：需求变化、用户可见行为、安全/合规、跨模块接口、成本超阈、争议 → 必须升级。

## 存放

- 阶段 PLAN 的“决策清单/未决项”附录；
- 或 CHG / ADR；
- 不把决策留在对话里。
""",
    "DEV-RECORD.md": """# DEV-RECORD <task-id>

## 目标

## 设计引用

## 实现摘要

## 关键决策

## 变更文件

## 测试

## 偏差与限制

## 证据

## 交接引用
""",
    "VERIFICATION-RECORD.yaml": """id: VR-0001
layer: implementation      # implementation|design|requirement
scope: ...
requirement_refs: [REQ-0001]
design_refs: [SPEC-001, DESIGN-001]
task_refs: [R1-P3-T001]
method: automated          # automated|artifact|demonstration|metric
result: PASS               # PASS|PASS_WITH_RISK|FAIL|BLOCKED
evidence: []
bugs: []
verifier: ...
date: ...
notes: ...
""",
    "HANDOFF.md": """# HANDOFF <task-id>

## 完成摘要

## 变更文件

## 验证结果（逐项对应 acceptance）

## 缺陷

## 纠正与经验

## 未决问题

## 下一步建议

## 证据索引

## fix 任务补充

### 根因

### 修复

### 回归证据
""",
    "CHG.md": """# CHG-0001 <标题>

> status: proposed
> approved_by:
> date:

## 原因

## 影响范围

## 受影响 REQ/SPEC/TASK

## 决策

## 实施与验证
""",
    "REVIEW.md": """# REVIEW-<task-id>

> reviewer:
> date:
> scope:
> verdict: PASS | PASS_WITH_RISK | NEEDS_REWORK | BLOCKED
> rework_scope: in-scope | out-of-scope | disputed
> rework_requires: none | acceptance,bug,mfp,chg
> rework_summary.reason:
> rework_summary.risk:
> rework_summary.impact:
> rework_summary.expectation:

## 评审对象

## 检查清单

- [ ] 目标/需求覆盖
- [ ] 设计规格一致性
- [ ] 接口/数据契约
- [ ] 测试与证据充分性
- [ ] 安全/权限边界
- [ ] 越界修改（diff 是否只在 allowed_paths）
- [ ] 可维护性与异常处理

## 发现

| ID | 严重级别 | 位置 | 问题 | 建议 |
|---|---|---|---|---|
| | | | | |

## 结论

结论：PASS | PASS_WITH_RISK | NEEDS_REWORK | BLOCKED

## 必须整改项

表格或小节二选一；小节写作 `### R4（in-scope）<要求>`，全角/半角括号均可。

| ID | 文件/行 | 要求 | 验收方法 |
|---|---|---|---|
| | | | |

## 证据
""",
    "REVIEW-HANDOFF.md": """# REVIEW-HANDOFF <task-id>

> reviewer:
> date:
> verdict: PASS | PASS_WITH_RISK | NEEDS_REWORK | BLOCKED
> rework_scope: in-scope | out-of-scope | disputed
> rework_requires: none | acceptance,bug,mfp,chg
> rework_summary.reason:
> rework_summary.risk:
> rework_summary.impact:
> rework_summary.expectation:

## 评审范围

## 评审结论

## 发现

| ID | 严重级别 | 文件/行 | 问题 | 建议 |
|---|---|---|---|---|
| | | | | |

## 必须整改项

表格或小节二选一；小节写作 `### R4（in-scope）<要求>`，全角/半角括号均可。

| ID | 文件/行 | 要求 | 验收方法 |
|---|---|---|---|
| | | | |

## 复审要求

## 下一步

- 范围内整改：评审提交 NEEDS_REWORK 后工具自动回流（目标 rejected/rework），worker 用 `mf task rework <task-id>` 开始；manager accept 只确认 verdict。
- 范围外/新 acceptance/BUG/MFP/CHG/争议：在 `rework_requires` 标注并开单，不阻塞范围内返工。
- NEEDS_REWORK 必须写 `rework_summary` 人话说明（原因/风险/影响/期望），缺失不得提交。
- 不得留空下一责任；与 verdict/rework_scope 保持一致。

## 证据
""",
    "MFP.yaml": """id: MFP-0001
title: ...
status: draft              # draft|submitted|triaged|accepted|implementing|implemented|verified|closed|rejected|deferred|duplicate
priority: should           # must|should|could
category: feature          # bug|feature|usability|template|cli|install|docs|platform
classification: undecided  # bug|requirement|change|undecided

source:
  project: ...
  role: manager            # manager|worker|user
  created_by: ...
  created_at: ...
  mf_version: 0.1.0
  platform: linux
  agent: manager

problem: ...
context:
  scenario: ...
  reproduction: []
  expected: ...
  actual: ...
  evidence: []
  affected: []

acceptance: []
testing_plan: ...
rollback: ...
privacy:
  sanitized: true
  removed: []

source_record: null
resolution:
  version: null
  commit: null
  tests: []
  verified_by: null
  verified_at: null
  note: null
""",
}
