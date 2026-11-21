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
- 维护 14 份规范。
- 编排设计、任务卡、wave、验收；维护分层验证与追踪矩阵。
- 维护系统架构、ADR、端到端规格与跨库契约。

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

| 路标 | 版本范围 | 首发 |
|---|---|---|
| R0 | 0.x.y | 0.1.0 |
| R1 | 1.x.y | 1.0.0 |
| R2 | 2.x.y | 2.0.0 |

## 规则

- 破坏性变更 → 新路标，MAJOR + 1。
- 兼容新增 → 同路标 MINOR + 1。
- 修复 → PATCH + 1，不新开路标。
- 阶段预发布：`alpha`（P3）、`beta`（P4）、`rc`（P5）。
- 外部合同编号（如 `V01R01C00`）只写入发布说明，不作为内部真相。

`mf release freeze` 校验路标编号与版本 MAJOR 一致。
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

每阶段进入前生成 `PHASE-PLAN`：目标、入口条件、WBS、任务/wave、过程交付件、验证计划、时间、风险、退出条件。

## 关闭与刷新

P5 结束：`mf roadmap close` → 关闭报告 → 未完成项转 R2/backlog → R2 计划 → 用户确认。
""",
    "DESIGN.md": """# DESIGN — 设计与规格规范

## 规格 SPEC

模板 `contracts/templates/SPEC.md`。必含：背景、范围/非目标、需求（EARS/Given-When-Then）、接口、数据、验收场景、非功能、依赖、开放问题、追踪。

每条规格必须关联 REQ；规格是 L2 设计验证的对象。

## 设计 DESIGN

模板 `contracts/templates/DESIGN.md`。必含：上下文、模块、接口、数据、流程、异常、非功能、方案对比、风险、ADR、测试策略、迁移/回滚。

## ADR

模板 `contracts/templates/ADR.md`。决策、背景、备选、后果、状态。

## 质量

可实施、可测试、无未决冲突；高风险设计必须独立 `review` 任务。
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

| 阶段 | 目标 | 退出条件 |
|---|---|---|
| P1 计划 | 端到端计划 | 用户确认；需求覆盖路标范围 |
| P2 设计 | 规格与架构基线 | 设计评审通过；接口/数据/测试设计可实施 |
| P3 实施 | 按任务卡交付 | 所有任务 PASS 或 WAIVED；无阻塞缺陷 |
| P4 试运行 | 端到端验证与用户试用 | 回归通过；用户试用通过；缺陷关闭/接受 |
| P5 发布 | 发布与归档 | 发布清单完成；版本冻结；用户批准；路标刷新 |

## 项目计划

P1 必须生成 `project/PROJECT-PLAN.md`：项目目标、最终交付件与能力、交付库、P1–P5 过程交付件、能力地图。P1 退出前用户确认；P5 逐项核对最终交付件能力。

## 阶段计划

每阶段进入前生成 `contracts/roadmap/phases/R{n}-P{n}-PLAN.md`：目标、入口、WBS、任务/wave、过程交付件、验证计划、时间、风险、退出条件。

## 用户门禁

- 必须：路标规划、P1 退出、P4 退出、P5 退出。
- 高风险/架构变更：P2 退出。
- P3 由 manager 逐卡验收，不打断用户。

## 阶段报告

退出时生成 `contracts/roadmap/phases/R{n}-P{n}-REPORT.md`：目标核对、L1/L2/L3 验证结果、缺陷、知识、下一阶段调整建议、路标影响、用户确认记录。

## 路标刷新

P5 结束后：`mf roadmap close R{n}` → `mf roadmap plan R{n+1}`。
""",
    "TASK-CARD.md": """# TASK-CARD — 任务卡规范

## 字段

- `id`：`R{路标}-P{阶段}-T{序号}`。
- `kind`：`implement|design|verify|document|review|fix`。
- `delivery`：所属交付库。
- `wave`：并行波次。
- `depends_on`：前置任务。
- `inputs.contracts`：引用的契约 ID。
- `allowed_paths` / `forbidden`：写路径边界。
- `deliverables`：交付物清单。
- `acceptance`：验收项（见 ACCEPTANCE）。
- `handoff`：是否要求交接文件。

## 任务就绪标准（DoR）

1. 单一、明确的结果。
2. 输入已列出且存在。
3. 交付物路径/格式明确。
4. 验收项可执行/可判定。
5. `allowed_paths` / `forbidden` 明确。
6. 依赖已 accepted 或不存在。
7. 交付库有效，wave 内无写冲突。
8. 规模一次 worker 会话可完成；过大拆分。
9. `risk` / `authorization` 已设置。
10. 无未决澄清问题。

不满足不得 `ready`；worker 可 `BLOCKED` 并指出缺项。模板：`contracts/templates/TASK.yaml`。

## 状态机

```text
draft → ready → in_progress → submitted → accepted | rejected
rejected → in_progress（返工）
```

## 并行

- 同一 wave 内不得写同一路径。
- 不同交付库天然可并行。
- `verify` / `review` 必须派给未参与实现的 worker。

## 禁止

- worker 不得修改验收标准。
- manager 不得事后追加验收项；返工开新卡或 `CHG-*`。
""",
    "ACCEPTANCE.md": """# ACCEPTANCE — 验收规范

## 原则

1. 验收标准前置，任务卡创建时写定。
2. 每项可判定：方法、命令、期望、证据。
3. worker 自验只作为提交证据；manager 必须独立复核。
4. 提交时校验 diff 是否在 `allowed_paths` 内。
5. 每条结果绑定证据 digest；证据缺失不得 PASS。
6. 结论只能是 `PASS / PASS_WITH_RISK / NEEDS_REWORK / BLOCKED`。
7. `PASS_WITH_RISK` 必须写风险、影响、接受人。
8. 阶段验收 = 任务验收汇总 + 阶段目标核对 + 开放风险 + 用户确认。

## 方法

| 方法 | 适用 | 证据 |
|---|---|---|
| automated | 代码/CLI/schema | 命令、退出码、日志 |
| artifact | 文档/设计/配置 | 文件 + schema/内容检查 |
| demonstration | 用户可见行为 | 步骤 + 观察结果 |
| metric | 性能/覆盖率 | 指标报告 |

## 独立性

高风险任务必须有 `verify` 或 `review` 任务，由另一个 worker 执行。

## Definition of Done

- 任务 DoD：实现 + 测试 + 开发记录 + 交接 + L1 证据；fix 任务含根因/修复/回归；文档任务含内容标准。
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

每个任务写 `.metaflow/dev-records/<task>.md`：目标、设计引用、实现摘要、关键决策、变更文件、测试、偏差、限制、证据、handoff 引用。

`mf task submit` 固化到 `contracts/dev-records/`；manager 作为 L1 证据审核。

## worker 遵守

- 读任务包、PROJECT-PLAN、相关 SPEC/DESIGN、TASK-CARD/DEVELOPMENT/VERIFICATION/ACCEPTANCE、KNOWLEDGE。
- 只写 `allowed_paths`；不写契约库；不跨交付库。
- 先确认任务就绪；不清晰则 `BLOCKED`。
- 完成实现 + 测试 + 开发记录 + 交接再提交。

## 交接

完成后写 `.metaflow/handoffs/<task-id>.md`：

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

`REQ → SPEC/DESIGN → TASK → DEV-RECORD → VR(L1/L2/L3) → BUG → RELEASE`。

`mf req trace` 显示三层验证状态；`mf doctor` 检查孤儿 REQ、未关联任务、缺失验证层。

## 证据

- 自动化：命令、退出码、输出日志。
- 文档/设计：文件 + schema/内容检查。
- 演示：步骤、观察结果、截图/录屏。
- 指标：报告、阈值、对比基线。

## 失败处理

- `NEEDS_REWORK`：回到当前任务，开返工卡或原卡返工。
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
    "DOCUMENTATION.md": """# DOCUMENTATION — 文档规范

## 单一真相源

- 需求、路标、计划、状态、架构、设计、端到端契约：`contracts/`。
- 交付库只保存自己的源码、发布件、发布说明、用户手册。
- 跨库共享内容必须放契约库，其他文档引用 ID，不复制正文。

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
| 设计 | `architecture/DESIGN-*.md` | `DESIGN.md` | manager/design | P2 |
| 架构决策 | `architecture/ADR-*.md` | `ADR.md` | manager/design | P2 |
| 任务 | `tasks/.../T*.yaml` | `TASK.yaml` | manager | P3 |
| 开发记录 | `dev-records/T*.md` | `DEV-RECORD.md` | worker | P3 |
| 验证记录 | `verification/VR-*.yaml` | `VERIFICATION-RECORD.yaml` | manager/verifier | P3/P4 |
| 交接 | `handoffs/T*.md` | `HANDOFF.md` | worker | P3 |
| 缺陷 | `bugs/BUG-*.yaml` | `BUG.yaml` | manager | P3/P4 |
| 变更 | `requirements/changes/CHG-*.md` | `CHG.md` | manager | 任意 |
| 评审 | `reviews/REVIEW-*.md` | `REVIEW.md` | reviewer | 任意 |

## Front matter

文档建议包含：`id`、`type`、`status`、`version`、`owner`、`roadmap`、`phase`、`updated_at`、`refs`。

## 写作

- 中文为主，标识符保持英文。
- 先结论后细节；可判定优先于描述。
- 不写本机绝对路径、凭据、临时日志。
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

ARTIFACT_TEMPLATES = {
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

## 工作分解（WBS）

| 工作项 | 交付库 | 负责人 | 依赖 | 交付件 |
|---|---|---|---|---|
| | | | | |

## 任务与 wave

## 验证计划（L1/L2/L3）

## 时间与里程碑

## 风险

## 退出条件
""",
    "PHASE-REPORT.md": """# R{n}-P{n} 阶段报告

## 阶段目标核对

## 需求覆盖

## L1/L2/L3 验证结果

## 过程交付件与证据

## 缺陷与未决问题

## 用户纠正与知识沉淀

## 下一阶段调整建议

## 路标影响

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
delivery: app
wave: W1
depends_on: []
status: draft             # draft|ready|in_progress|submitted|accepted|rejected|cancelled
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
risk: medium
authorization:
  network: false
  production_write: false
  credentials: false
deliverables:
  - path: src/...
  - path: tests/...
acceptance:
  - id: A1
    method: automated
    command: ...
    expect: exit_code=0
handoff: required
dev_record: required
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

## 评审对象

## 发现

| ID | 严重级别 | 位置 | 问题 | 建议 |
|---|---|---|---|---|
| | | | | |

## 结论

## 证据
""",
}
