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
- 维护路标、版本、阶段；组织 P1–P5。
- 维护 9 份规范。
- 编排设计、任务卡、wave、验收。
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
- 完成自验，写交接文件，用 `mf task submit` 提交。

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
- 完成后写交接文件并提交，等待 manager 验收。
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

## 追踪

`mf req trace REQ-0001` 输出：

```text
REQ-0001 → R1 → P1/P3 → SPEC-xxx → TASK-xxx → 验收记录 → 发布版本
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

## 用户门禁

- 必须：路标规划、P1 退出、P4 退出、P5 退出。
- 高风险/架构变更：P2 退出。
- P3 由 manager 逐卡验收，不打断用户。

## 阶段报告

`mf phase review` 生成 `PHASE-REPORT`：目标核对、需求覆盖、证据、风险、下阶段调整建议、路标影响、用户确认记录。

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

## 交接

完成后写 `.metaflow/handoffs/<task-id>.md`：

1. 完成摘要
2. 变更文件
3. 验证结果（逐项对应 acceptance）
4. 未决问题
5. 下一步建议
6. 证据索引
""",
    "VERIFICATION.md": """# VERIFICATION — 验证规范

## 层级

1. **任务自验**：worker 运行任务卡自动项，提交证据。
2. **manager 验收**：独立重跑自动项、抽查证据、判定结论。
3. **阶段验证**：P4 端到端回归 + 用户试用。
4. **发布验证**：P5 发布清单、版本冻结、证据归档。

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

## Front matter

文档建议包含：`id`、`type`、`status`、`version`、`owner`、`roadmap`、`phase`、`updated_at`、`refs`。

## 写作

- 中文为主，标识符保持英文。
- 先结论后细节；可判定优先于描述。
- 不写本机绝对路径、凭据、临时日志。
""",
}

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
