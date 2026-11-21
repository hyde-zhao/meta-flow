# Meta Flow v1 设计文档

```yaml
status: draft
version: 0.1
date: 2026-11-21
owner: hyde
product: Meta Flow
cli: mf
supersedes: meta-flow v0.x（归档，不再演进）
```

## 0. 文档目的

本文是 Meta Flow v1 的第一个契约，定义产品定位、角色边界、工作区结构、版本体系、五阶段流程、任务卡与验收协议、并行编排、状态 CLI 和路线图。

v1 不再是一个“工作流产物工厂”，而是一个 **AI 项目操作系统**：用三个角色管理一个由契约库和多个交付库组成的项目，以规格驱动交付。

---

## 1. 产品定位

### 1.1 从 v0 到 v1

| 维度 | v0（归档） | v1 |
|---|---|---|
| 核心对象 | 工作流、Agent、Skill、CP0–CP8 | 项目、路标、版本、阶段、模块、任务卡 |
| 角色 | 6 个功能 Agent + Host Orchestrator + profiles | 3 个角色：maintainer / manager / worker |
| 治理 | CR、checkpoint、ledger、projection、context capsule | 路标 + 五阶段 + 任务卡 + 验收记录 |
| 状态 | 多文件投影 + 派生状态 | 文件真相 + 单一 CLI + 追加 ledger |
| 规格 | 产品/设计/Story/LLD 多层文档 | 契约库中的 SPEC/DESIGN + 任务卡 |
| 交付 | 工作流资产包 | 契约库 + 一个或多个交付库 |

### 1.2 目标

1. 用户只面对一个角色：`meta-manager`。
2. manager 用路标、版本、五阶段管理项目，而不是用 CP0–CP8。
3. worker 只接收任务卡，在独立上下文里执行，提交交接文件。
4. 契约库是项目公共真相源；交付库是完整交付单元；跨库信息只走契约库。
5. 状态由 CLI 统一读写的文本文件承载，可用 git 审计。
6. 并行任务由 manager 规划为 wave，多个 worker 独立推进。
7. 安装、升级、初始化、验收都有明确流程。

### 1.3 非目标

- 不做 Web UI、SaaS、多租户。
- 不迁移 v0 项目；v0 项目留在旧仓。
- 不恢复 CP0–CP8、CR/ledger/projection 全套治理。
- 不自动发布、不自动 push、不自动改生产。
- 不做 Skill 市场或插件生态。

### 1.4 设计原则

1. **角色是权限边界，不是人格**：每个角色只写自己该写的地方。
2. **验收标准先于实现**：任务卡创建时写定，worker 不可修改。
3. **文件是真相，CLI 是唯一写入口**：派生状态可重建。
4. **任务包自包含**：worker 用全新会话也能独立完成任务。
5. **契约库是消息总线**：manager 与 worker 不直接互读对方仓库。
6. **默认轻量，例外显式**：高风险、多交付库、外部合同才增加复杂度。
7. **命令预算**：核心命令约 30 个，缺陷/知识/维护扩展不超过 10 个；每个命令必须有明确角色和门禁用途。

---

## 2. 三角色

### 2.1 角色表

| 角色 | 中文 | 面向 | 核心职责 | 可写范围 | 禁止 |
|---|---|---|---|---|---|
| `meta-maintainer` | 维护者 | 工作区 / 工具 | 建仓、安装 agent、`mf doctor/upgrade`、跨仓健康；在工具源码仓维护 CLI/模板/测试/发布 | 工作区清单、agent 安装、工具源码 | 需求、路标、任务验收、交付代码 |
| `meta-manager` | 项目管理者 | 用户 | 需求对齐、模块规划、路标、版本、五阶段、规范、任务卡、wave 规划、验收、路标刷新 | `contracts/` 全部；任务卡与验收记录 | 交付库源码；事后修改验收标准 |
| `meta-worker` | 执行者 | 任务卡 | 领取任务包、执行、自验、写交接、提交证据 | 自己交付库的 `allowed_paths`；自己的任务状态 | 契约库、其他交付库、路标/需求/阶段；直接问用户 |

### 2.2 两个作用域的 maintainer

`meta-maintainer` 有两个作用域，同一角色定义：

1. **工作区维护者**：工作区根目录。负责两仓初始化、agent 安装、工具升级、`mf doctor`、跨仓健康。不碰项目需求和交付代码。
2. **工具维护者**：meta-flow 源码仓。负责 CLI、模板、agent 定义、安装器、测试、版本发布。手动安装，不由 `mf setup` 自动安装。

### 2.3 目录级默认角色

平台事实：Claude Code 没有“按 cwd 自动切换主 agent”的原生开关。v1 用三层实现等价效果：

| 层 | 机制 | 作用 |
|---|---|---|
| 1 | 目录级 `CLAUDE.md` / `AGENTS.md` | 根目录 = maintainer；`contracts/` = manager；`deliveries/**` = worker。子目录文件显式声明父级角色不适用。 |
| 2 | SessionStart hook | 读取 cwd，写 `.metaflow/session-role.json`，打印角色横幅；agent 第一条规则是读取它。 |
| 3 | CLI 强制 | `mf` 每个命令检查 cwd、`MF_ROLE`、路径白名单；越权命令拒绝。 |

| 目录 | 默认角色 | 允许 | 禁止 |
|---|---|---|---|
| 工作区根目录 | `meta-maintainer` | `mf init/setup/doctor/upgrade/agent/worker install`、工作区清单 | `mf req`、`mf roadmap`、`mf task accept`、改 contracts/deliveries |
| `contracts/` | `meta-manager` | 契约库读写、任务卡、验收、wave 规划 | 交付库源码 |
| `deliveries/**` | `meta-worker` | 任务包读取、`allowed_paths` 内写入、任务提交 | 契约库、其他交付库、路标/需求 |

补充：

- `mf role` 显示当前目录推导出的角色。
- `mf status --role` 可按角色裁剪视图。
- 如果平台支持指定主 agent 的启动参数，`mf claude` 启动器可作为可选硬入口；不作为默认路径。
- 角色路由的最终安全边界在 CLI 和 hook，不在 agent 名字。

### 2.4 设计工作：任务类型，不新增角色

设计是工作类型，不是权限边界。v1 先不加 `meta-designer`。

- 设计任务使用 `kind: design`，由 `meta-worker` 执行。
- 输出写 `contracts/architecture/drafts/<task-id>/`（任务卡显式允许）。
- manager 验收后，把草案提升为 `contracts/architecture/` 的正式文档。
- 高风险设计加一个 `kind: review` 任务，由另一个 worker 独立评审。
- 如果 R2 发现设计长期占满 manager，再引入可选的 `meta-designer`，权限限定为架构/规格草案，不碰需求、路标、任务、验收。

设计任务验收清单：

1. 需求覆盖（REQ ID 逐条映射）。
2. 候选方案与 trade-off。
3. 接口/数据契约。
4. 风险与缓解。
5. 可测试性。
6. 与现有架构/ADR 一致性。
7. 迁移/回滚（如适用）。

### 2.5 平台支持节奏

| 平台 | R1 | R2 |
|---|---|---|
| Claude Code | ✓ | ✓ |
| DeepSeek Harness (DSH) | - | ✓ |
| Codex | - | ✓ |

R1 只实现 Claude Code 适配；R2 增加 DSH 与 Codex。角色定义、任务卡、契约、CLI 保持平台无关；平台差异只放在安装器/路径适配层，避免把 Claude 特有行为写进核心。R1 的 `agents/*.md` 保持 Claude 可安装格式；R2 拆出 canonical 角色正文与平台 frontmatter。

---

## 3. 工作区与仓库

### 3.1 两仓布局

v1 默认两个 git 仓库：

```text
workspace/                     # 容器目录，不必是 git 仓
├── mf.workspace.yaml          # 可选清单；mf 可自动发现，可重建
├── CLAUDE.md                  # maintainer 角色
├── AGENTS.md                  # Codex 角色
├── contracts/                 # git repo A：契约库
│   ├── CLAUDE.md              # manager 角色
│   ├── AGENTS.md
│   ├── .metaflow/role.yaml    # role: manager
│   ├── project.yaml
│   ├── project/
│   │   └── PROJECT-PLAN.md    # 过程、过程交付件、最终交付件能力
│   ├── roadmap/ROADMAP.yaml
│   ├── requirements/REQUIREMENTS.yaml
│   ├── standards/             # 11 份规范
│   ├── architecture/          # 架构图、ADR、端到端设计
│   ├── specs/                 # 端到端规格、跨库接口/数据契约
│   ├── tasks/R1/P3/T013.yaml
│   ├── verification/
│   ├── handoffs/              # 由 mf 固化的交接副本
│   ├── state/
│   │   ├── ledger.ndjson      # 追加式事件日志（tracked）
│   │   └── current.json       # 派生缓存（gitignore，可重建）
│   └── archive/               # 版本结束归档
└── deliveries/                # git repo B：交付库集合
    ├── CLAUDE.md              # worker 角色
    ├── AGENTS.md
    ├── .metaflow/role.yaml    # role: worker
    ├── frontend/
    │   ├── CLAUDE.md          # 本交付库的 worker 约束
    │   ├── delivery.yaml
    │   ├── src/
    │   ├── tests/
    │   ├── release/           # 构建产物、发布件
    │   ├── RELEASE-NOTES.md
    │   └── USER-MANUAL.md
    └── backend/
        └── ...
```

为什么是两仓：

- contracts 仓是项目公共真相和跨库集成点。
- deliveries 仓是所有交付库的实现与发布物。
- 两仓给出清晰的 git/发布边界。
- 如果 frontend/backend 将来需要独立发布节奏或不同团队权限，再拆成三个仓；R0/R1 不拆。

说明：以上是 meta-flow **管理的项目**的工作区布局。meta-flow 自身只有一个交付物——`meta-flow` 工具包（CLI、agents、templates），不使用 `deliveries/`；其版本遵循工具 SemVer 与 R0/R1/R2 路标。

### 3.2 契约库职责

契约库存放：

- 项目元数据、模块/交付库注册表、当前路标与阶段。
- 项目计划 `PROJECT-PLAN.md`：过程、过程交付件、最终交付件能力。
- 路标、需求、变更单、追踪矩阵。
- 11 份项目规范。
- 系统架构图、ADR、端到端设计。
- 端到端规格、跨交付库接口/数据契约。
- 任务卡、验收记录、交接副本、事件 ledger。
- 版本结束归档。

契约库不存放：

- 交付库的私有源码、构建产物、私有实现设计。
- 交付库的用户手册/发布说明正文（副本或引用可以）。

### 3.3 交付库职责

每个交付库是完整交付单元：

- 源码与测试。
- 构建/发布产物。
- `RELEASE-NOTES.md`。
- `USER-MANUAL.md`。
- `delivery.yaml`：标识、版本、责任、引用的契约、产物清单、文档路径、仓库位置。

交付库之间不直接引用；共享接口/数据契约必须放契约库。

### 3.4 跨库信息流

```text
manager 在 contracts 写任务卡与契约
        │
        ▼
mf task show --packet  →  worker 只看到任务包
        │
        ▼
worker 在 delivery 内执行、写交接与证据
        │
        ▼
mf task submit  →  证据/交接摘要固化到 contracts/verification 与 contracts/handoffs
        │
        ▼
manager 在 contracts 验收，mf task accept/reject
        │
        ▼
mf task prompt 生成下一任务提示词
```

契约库是消息总线；manager 不读交付库源码，worker 不读契约库全文。

### 3.5 上下文隔离三层

1. **角色会话隔离**：根目录、`contracts/`、`deliveries/` 三个入口，各自只有自己的角色指令和读写白名单。
2. **任务上下文隔离**：`mf task show --packet` 只返回任务卡 + 声明的契约片段 + 允许路径；`mf task submit` 把证据摘要和交接固化进契约库。
3. **路径守卫**：hook 拦截越界 Read/Write/Edit；`mf task submit` 校验 `git diff --name-only` 是否在 `allowed_paths` 内；越界拒绝。

这三层比“多拆几个仓库”更有效地防止幻觉和上下文污染；仓库数量只解决 git/发布边界。

---

## 4. 版本与路标

### 4.1 双轨

| 对象 | 编号 | 说明 |
|---|---|---|
| 工具 | SemVer | `meta-flow` 自身：`v1.0.0`、`v1.1.0`、`v2.0.0` |
| 路标 | `R{n}` | 规划单位：`R0`、`R1`、`R2`；可选年份前缀 `2026.R1` |
| 项目交付 | SemVer | 项目版本 = 路标版本：`R1 → 1.x.y` |
| 交付库 | SemVer | 仅用于被管理项目；`project.yaml.version_policy` 决定 `same-major` / `exact` / `independent`；meta-flow 自身交付物是 CLI 包，版本 = 工具 SemVer |
| 阶段预发布 | SemVer prerelease | `1.0.0-alpha.N`（P3）、`-beta.N`（P4）、`-rc.N`（P5） |
| 任务 | 复合 ID | `R1-P3-T013` |
| 需求 | 稳定 ID + 路标字段 | `REQ-0001`，`roadmap: R1` |
| 变更 | `CHG-{序号}` | `CHG-0001` |
| 外部合同映射 | 可选 | `V01R01C00` 等，仅写入发布说明，不参与内部排序 |

### 4.2 映射规则

> **路标 `R{n}` 拥有主版本号 `n`。`R{n}` ↔ `n.x.y`。**

| 路标 | 版本范围 | 首发 | 阶段预发布 | 补丁 |
|---|---|---|---|---|
| R0 骨架 | `0.x.y` | `0.1.0` | `0.1.0-alpha/beta/rc.N` | `0.1.x` |
| R1 MVP | `1.x.y` | `1.0.0` | `1.0.0-alpha/beta/rc.N` | `1.0.x` |
| R2 规模化 | `2.x.y` | `2.0.0` | `2.0.0-alpha/beta/rc.N` | `2.0.x` |

升降规则：

- 破坏性变更 → 新路标，MAJOR + 1。
- 向后兼容新增 → 同一路标 MINOR + 1。
- 修复 → PATCH + 1，不新开路标。
- 路标内不允许破坏性变更。

`contracts/roadmap/ROADMAP.yaml` 显式记录：

```yaml
schema: 1
roadmaps:
  - id: R1
    title: MVP
    status: active
    version_range: "1.x"
    version_target: "1.0.0"
    goal: ...
    entry_criteria: [...]
    exit_criteria: [...]
    non_goals: [...]
  - id: R2
    title: 规模化
    status: planned
    version_range: "2.x"
    version_target: "2.0.0"
```

`mf release freeze` 校验当前路标编号等于项目版本 MAJOR；不一致拒绝。

### 4.3 外部版本映射

如果客户合同要求 `V01R01C00`：

```yaml
external_versions:
  - roadmap: R1
    project_version: 1.0.0
    external: V01R01C00
```

`external` 只出现在发布说明书和合同文档，不参与 CLI 排序、依赖解析或 git tag。

---

## 5. 五阶段与门禁

### 5.1 阶段表

| 阶段 | 目标 | 进入条件 | 退出条件 | 主要产出 | 非目标 |
|---|---|---|---|---|---|
| **P1 计划** | 端到端计划 | 需求草案 + 路标草案 | 用户确认；REQ 覆盖 R 范围；任务可估算 | 计划、需求基线、路标映射、验收策略 | 详细架构 |
| **P2 设计** | 规格与架构基线 | P1 退出 | 设计评审通过；接口/数据/测试设计可实施 | SPEC、DESIGN、ADR、TEST-PLAN | 产品代码 |
| **P3 实施** | 按任务卡交付 | P2 退出 | 所有任务 PASS 或 WAIVED；无阻塞缺陷 | 代码、测试、验收记录 | 发布 |
| **P4 试运行** | 端到端验证与用户试用 | P3 退出 | 回归通过；用户试用通过；缺陷关闭/接受 | 验证报告、UAT、回归记录 | 新增范围 |
| **P5 发布** | 发布与归档 | P4 退出 | 发布清单完成；版本冻结；用户批准；路标刷新 | 发布说明、用户手册、release.yaml、R 关闭报告 | 下一版本开发 |

### 5.2 用户门禁

| 门 | 是否必须 | 说明 |
|---|---|---|
| 路标规划（R） | 必须 | 用户确认目标、范围、非目标、版本目标 |
| P1 退出 | 必须 | 用户确认端到端计划 |
| P2 退出 | 高风险/架构变更必须 | 普通设计可由 manager 验收 |
| P3 退出 | 不需要用户逐卡 | manager 逐卡验收；阶段报告汇总 |
| P4 退出 | 必须 | 用户试用验收 |
| P5 退出 | 必须 | 用户批准发布 |

一个版本 3–4 次人工门，避免门禁疲劳。

### 5.3 阶段报告

每个阶段结束生成 `PHASE-REPORT`：

```text
# PHASE-REPORT R1-P3
1. 阶段目标核对（逐条目标 → 达成/未达成/证据）
2. 需求覆盖（REQ → 任务 → 验收）
3. 交付物与证据清单
4. 未决问题、风险、技术债
5. 下一阶段计划调整建议
6. 路标影响与刷新建议
7. 用户确认记录
```

`mf phase review` 生成草案；manager 补充判断；用户确认后 `mf phase exit` 推进。

### 5.4 路标刷新

版本结束固定动作：

1. `mf phase exit` 完成 P5。
2. `mf release freeze` 写发布清单。
3. `mf roadmap close R1`：核对 REQ 状态、生成 R1 关闭报告、未完成项转入 R2/backlog。
4. `mf roadmap plan R2`：manager 起草下一路标目标/范围/进入退出条件，用户确认。
5. `mf status` 显示新路标。

### 5.5 项目过程与交付件规划

manager 在 P1 必须与用户确认并写入 `contracts/project/PROJECT-PLAN.md`：

1. 项目目标、成功指标、非目标。
2. 最终交付件清单与能力：每个交付件“能做什么”、对应 REQ、验收方式。
3. 交付库划分：职责、最终产物、版本策略。
4. 过程计划：P1–P5 每阶段的目标、过程交付件、退出条件。
5. 能力地图：能力 → REQ → 验收场景 → 交付件。
6. 风险、假设、变更记录。

门禁：

- P1 退出前用户确认 PROJECT-PLAN。
- 每个阶段退出时核对本阶段过程交付件。
- P5 退出时逐项核对最终交付件能力；缺项必须返工或由用户显式接受。

版本策略写在 `project.yaml.version_policy`：

| 值 | 含义 |
|---|---|
| `same-major` | 交付库与项目同 MAJOR（R1 默认） |
| `exact` | 交付库版本必须等于项目版本 |
| `independent` | 交付库完全独立，需在契约库声明兼容范围（R2） |

---

## 6. 需求与追踪

### 6.1 REQ 对象

```yaml
id: REQ-0001
title: 用户可以初始化工作区
source: user
priority: must            # must|should|could
status: accepted          # proposed|accepted|in_roadmap|in_progress|verified|released|deferred
roadmap: R1
acceptance:
  - 初始化后存在 contracts/ 与 deliveries/
  - mf doctor 通过
trace:
  specs: [SPEC-INIT-001]
  tasks: [R1-P3-T001]
  verification: [VR-0001]
```

### 6.2 追踪矩阵

`mf req trace REQ-0001` 输出：

```text
REQ-0001 → R1 → P1/P3 → SPEC-INIT-001 → T001 → VR-0001 → 1.0.0
```

路标关闭时，`mf roadmap close` 检查每条 REQ 是否处于 `verified/released/deferred`，否则阻止关闭或要求显式降级。

### 6.3 变更单

基线后的需求变更使用 `CHG-{序号}`：

```yaml
id: CHG-0001
title: 增加离线安装
reason: 客户现场无网络
affected: [REQ-0007, SPEC-INSTALL-001]
impact: 中
decision: accepted        # proposed|accepted|rejected|deferred
approved_by: user
```

变更单放 `contracts/requirements/changes/`；版本结束时归档到 `contracts/archive/R{n}/changes/`。

---

## 7. 任务卡与并行编排

### 7.1 任务卡

```yaml
id: R1-P3-T013
title: 实现状态机
kind: implement           # implement|design|verify|document|review|fix
delivery: frontend
wave: W2
depends_on: [R1-P3-T010]
status: ready             # draft|ready|in_progress|submitted|accepted|rejected|cancelled
inputs:
  contracts: [SPEC-CLI-001]
  design: [DESIGN-STATE-001]
  standards: [TASK-CARD, ACCEPTANCE]
allowed_paths:
  - src/state/**
  - tests/state/**
forbidden:
  - contracts/**
  - ../backend/**
risk: medium
authorization:
  network: false
  production_write: false
  credentials: false
deliverables:
  - path: src/state/machine.py
  - path: tests/state/test_machine.py
acceptance:
  - id: A1
    method: automated
    command: uv run pytest tests/state/test_machine.py
    expect: exit_code=0
  - id: A2
    method: artifact
    target: src/state/machine.py
    expect: 状态转换枚举与 SPEC-CLI-001 一致
  - id: A3
    method: demonstration
    steps: [mf task start R1-P3-T013, mf task submit R1-P3-T013]
    expect: 状态依次为 in_progress/submitted
handoff: required
lease:
  owner: null
  expires_at: null
```

### 7.2 任务类型

| kind | 用途 | 典型产出 |
|---|---|---|
| `implement` | 代码/配置实现 | 源码、测试、构建脚本 |
| `design` | 架构/规格设计 | `contracts/architecture/drafts/<task>/` 草案 |
| `verify` | 独立验证 | 验证报告、证据 |
| `document` | 发布说明/用户手册 | `RELEASE-NOTES.md`、`USER-MANUAL.md` |
| `review` | 同行评审 | 评审报告 |
| `fix` | 返工 | 修复与回归证据 |

`verify` 和 `review` 必须派给未参与实现的另一个 worker。

### 7.3 任务状态机

```text
draft --(manager ready)--> ready --(worker start)--> in_progress
in_progress --(worker submit)--> submitted
submitted --(manager accept)--> accepted
submitted --(manager reject)--> rejected --(worker start)--> in_progress
ready --(manager cancel)--> cancelled
```

角色权限：

| 动作 | manager | worker |
|---|---|---|
| create / plan / ready | ✓ | - |
| prompt / graph / accept / reject / release | ✓ | - |
| list / show | 全部 | 仅本交付库 |
| start / submit | - | ✓ |
| 修改验收标准 | 禁止（只能返工/CHG） | 禁止 |

### 7.4 DAG、wave 与冲突检测

`mf task plan`：

1. 计算依赖图，拒绝环。
2. 把无依赖或依赖已 accepted 的任务列为 ready。
3. 按 `wave` 分组；同一 wave 内检查 `allowed_paths` 是否重叠。
4. 不同交付库的任务天然可并行；同一交付库内写路径重叠的任务串行。
5. 契约库写入只允许 manager；design 任务只写 draft 路径。

`mf task graph` 输出：

```text
W1: T010 (frontend) ✓
W2: T011 (frontend) ready | T013 (backend) ready | T014 (docs) ready
W3: T012 (frontend) blocked by T011
```

### 7.5 租约与并发

- `mf task start <id>` 写 lease：`owner`、`started_at`、`expires_at`。
- lease 未过期时，另一个 worker 不能 start。
- `mf task submit` 校验 lease owner 与证据。
- 超时或 worker 退出：manager 用 `mf task release <id> --force` 回收。
- `mf status` 显示活跃 lease、submitted 队列、阻塞任务。

### 7.6 交接文件

worker 在交付库写 `.metaflow/handoffs/<task-id>.md`，`mf task submit` 固化副本到 `contracts/handoffs/<task-id>.md`。

```markdown
# HANDOFF R1-P3-T013

## 完成摘要
## 变更文件
## 验证结果（逐项对应 acceptance）
## 未决问题
## 下一步建议
## 证据索引
```

必需章节缺失时 `mf task submit` 拒绝。

### 7.7 验收协议

`contracts/standards/ACCEPTANCE.md` 规定：

1. **验收标准前置**：任务卡创建时写定，worker 不可修改。
2. **可判定**：每项必须有 method / command / expect / evidence；主观描述必须转成 artifact 或 demonstration。
3. **独立性**：worker 自验只作为提交证据；manager 必须独立重跑自动项、抽查证据。
4. **范围校验**：`mf task submit` 比对 `git diff --name-only` 与 `allowed_paths`，越界拒绝。
5. **证据绑定**：每条结果绑定证据文件 digest；证据缺失或不可复现不得 PASS。
6. **结论枚举**：`PASS / PASS_WITH_RISK / NEEDS_REWORK / BLOCKED`；`PASS_WITH_RISK` 必须写风险、影响和接受人。
7. **不可事后加项**：验收中发现问题只能返工并开新卡或 `CHG-*`，不得临时追加标准。
8. **阶段验收** = 任务验收汇总 + 阶段目标逐条核对 + 开放风险清单 + 用户确认（按门禁策略）。

验收方法：

| 方法 | 适用 | 证据 |
|---|---|---|
| automated | 代码/CLI/schema | 命令、退出码、日志 |
| artifact | 文档/设计/配置 | 文件 + schema/内容检查 |
| demonstration | 用户可见行为 | 步骤 + 观察结果 + 截图/录屏 |
| metric | 性能/覆盖率 | 指标报告 |

### 7.8 下一任务提示词

`mf task prompt <id>` 输出标准提示词：

```text
你是 meta-worker，负责 frontend 交付库。
任务：R1-P3-T014（wave W2）
工作目录：.../deliveries/frontend
第一步：运行 mf task show R1-P3-T014 --packet
允许写：src/state/**, tests/state/**
禁止：contracts/**、backend/**、其他任务路径
完成后：mf task submit R1-P3-T014 --handoff .metaflow/handoffs/R1-P3-T014.md
```

manager 验收通过后，用 `mf task ready` 找解锁任务，再用 `mf task prompt` 生成下一条提示词。

### 7.9 缺陷跟踪

所有验证过程中发现的缺陷必须记录为 `BUG-*`，存放在 `contracts/bugs/`。缺陷是契约库的一等对象，不是任务卡里的备注。

#### 对象

```yaml
id: BUG-0001
title: 登录后状态未刷新
severity: blocker|critical|major|minor|trivial
status: open|triaged|in_progress|fixed|verifying|closed|reopened|deferred|wontfix
found_in:
  phase: P4
  task: R1-P4-T003
  verification: VR-0001
delivery: frontend
related_reqs: [REQ-0007]
environment: ...
steps: ...
expected: ...
actual: ...
evidence: [...]
fix_task: null
root_cause: null
changed_files: []
regression: []
resolution: null
```

#### 生命周期

```text
open → triaged → in_progress → fixed → verifying → closed
closed → reopened
open/triaged → deferred | wontfix（需理由和用户接受）
```

#### 与验证、任务联动

- `mf verify record --result FAIL` 必须带 `--bug BUG-*` 或 `--create-bug`；否则拒绝。
- `mf task reject` 若是交付行为缺陷，创建/关联 bug；只是未完成则写返工原因。
- 修复使用 `kind: fix` 任务，`fixes: [BUG-0001]`。
- fix 任务交接必须含 `## 根因`、`## 修复`、`## 回归证据`；`mf task submit` 校验。
- `mf task accept` 将 bug 置 `fixed`；`mf verify record --result PASS` 将 bug 置 `closed`。
- `mf phase exit P4` 检查 open blocker/critical；未关闭必须用户显式接受。
- `mf release freeze` 列出 fixed bugs 与 known issues；open blocker/critical 阻止发布。

#### CLI 与角色

| 命令 | manager | worker |
|---|---|---|
| `mf bug add/list/show/update/close` | ✓ | 只读本任务相关 |
| 交接 `## 缺陷` | 审核 | ✓ 上报 |

worker 不直接写契约库；在交接文件 `## 缺陷` 上报，由 manager `mf bug add` 记录。

#### 为什么不是 hook

缺陷有状态、链接、门禁和审计需求；hook 无法可靠判定“这是缺陷”或保存生命周期。hook 适合提醒，真相由 CLI 管理。

### 7.10 知识沉淀与纠正记录

manager 和 worker 都需要在与用户/上游交互中提炼知识，减少重复纠正，形成项目级默契。

#### 对象类型

| 类型 | 记录什么 | 示例 |
|---|---|---|
| `term` | 术语纠正 | “交付库”统一叫“交付库（delivery library）” |
| `behavior` | 行为纠正 | 用户说“先别写代码”时，先复述并确认 |
| `convention` | 项目约定 | 所有任务卡先写验收标准 |
| `preference` | 沟通/格式偏好 | 先给结论，再给理由 |
| `lesson` | 阶段/版本复盘 | 设计任务必须先确认接口契约 |

#### 存放

```text
contracts/knowledge/
├── KNOWLEDGE.yaml       # 结构化真相
├── KNOWLEDGE.md         # mf knowledge render 生成
└── LESSONS-R1.md        # 版本结束复盘
```

#### 记录时机与角色

- 用户纠正术语、行为、格式时，manager 立即 `mf knowledge add`。
- 用户拒绝方案并说明原因时，记录为 `behavior` 或 `convention`。
- 阶段结束 `mf phase review` 增加“用户纠正与知识沉淀”章节；版本结束 `mf roadmap close` 写 `LESSONS-R{n}.md`。
- worker 不直接写契约库；在交接 `## 纠正与经验` 上报，manager 审核后合并。
- 知识条目必须有 `source`（user/manager/worker）、日期、上下文。

#### 读取与注入

- manager 会话启动时读取 `KNOWLEDGE.md` 摘要。
- `mf task show --packet` 注入与任务/交付库相关的术语和约定。
- SessionStart hook 打印最近纠正、开放 bug 摘要；hook 只做注入，不做语义捕获。

#### 总结提炼

- `mf knowledge render` 生成人类可读版本。
- `mf phase review` 的 PHASE-REPORT 包含“用户纠正与知识沉淀”章节。
- `mf roadmap close` 生成 `LESSONS-R{n}.md`，作为下一路标输入。

#### 为什么不是纯 hook

用户纠正是自然语言，hook 无法可靠识别语义；记录由 agent 指令 + CLI 完成，hook 只负责把已有知识注入会话。

---

## 8. 状态与 CLI

### 8.1 文件真相与派生状态

| 类型 | 文件 | 是否 tracked | 说明 |
|---|---|---|---|
| 项目元数据 | `contracts/project.yaml` | 是 | 当前路标/阶段、交付库注册表 |
| 路标 | `contracts/roadmap/ROADMAP.yaml` | 是 | R0/R1/R2 |
| 需求 | `contracts/requirements/REQUIREMENTS.yaml` | 是 | REQ + CHG |
| 任务 | `contracts/tasks/R{n}/P{n}/T{id}.yaml` | 是 | 每任务一文件 |
| 验收 | `contracts/verification/<task>/` | 是 | 证据 manifest + 摘要 |
| 交接 | `contracts/handoffs/<task>.md` | 是 | 由 mf 固化 |
| 事件 | `contracts/state/ledger.ndjson` | 是 | 追加式审计 |
| 当前状态 | `contracts/state/current.json` | 否 | 派生缓存，可重建 |

`mf status` 在 `current.json` 缺失或过期时，从任务/路标/ledger 重建。

### 8.2 命令集

核心命令：

| 域 | 命令 |
|---|---|
| 初始化 | `mf init`、`mf status`、`mf role`、`mf doctor` |
| 路标 | `mf roadmap show`、`mf roadmap plan`、`mf roadmap close` |
| 阶段 | `mf phase enter`、`mf phase review`、`mf phase exit` |
| 需求 | `mf req add`、`mf req list`、`mf req trace` |
| 交付库 | `mf delivery list`、`mf delivery show` |
| 任务 | `mf task create`、`mf task list`、`mf task graph`、`mf task plan`、`mf task prompt`、`mf task show`、`mf task start`、`mf task submit`、`mf task accept`、`mf task reject`、`mf task release` |
| 缺陷 | `mf bug add`、`mf bug list`、`mf bug show`、`mf bug update`、`mf bug close` |
| 知识 | `mf knowledge add`、`mf knowledge list`、`mf knowledge show`、`mf knowledge render` |
| 验证 | `mf verify record` |
| 发布 | `mf release freeze` |
| 维护 | `mf log`、`mf upgrade`、`mf agent update`、`mf worker install` |

约定：

- `--json` 给 agent；默认表格给用户。
- 破坏性操作默认 dry-run，`--apply` 才写。
- 退出码：0 成功，1 校验失败，2 角色/权限拒绝，3 状态冲突。
- 所有写操作原子写 + 文件锁 + ledger 追加。

### 8.3 角色权限矩阵

| 命令域 | maintainer | manager | worker |
|---|---|---|---|
| init/setup/doctor/upgrade/agent/worker install | ✓ | - | - |
| roadmap/phase/req | - | ✓ | - |
| delivery list/show | ✓（read） | ✓ | ✓（本库） |
| task create/plan/graph/prompt/accept/reject/release | - | ✓ | - |
| task list/show | - | ✓（全部） | ✓（本库） |
| task start/submit | - | - | ✓ |
| bug add/list/show/update/close | - | ✓ | 只读（本任务相关） |
| knowledge add/list/show/render | - | ✓ | 只读（任务包注入） |
| verify record | - | ✓ | ✓（本人任务） |
| release freeze | - | ✓ | - |
| log | ✓ | ✓ | ✓（本人任务） |

### 8.4 ledger

每次状态转换追加一行：

```json
{"ts":"2026-11-21T12:00:00Z","actor":"meta-worker","role":"worker","command":"task.submit","object":"R1-P3-T013","from":"in_progress","to":"submitted","evidence_digest":"sha256:...","version":"1.0.0-alpha.1"}
```

`mf log --object <id>` 查询；`mf log --render` 生成 `HISTORY.md`。

---

## 9. 安装与升级

### 9.1 安装方式

用户从 GitHub 安装，不发布 PyPI：

```bash
# 用户：从 GitHub tag 安装；R0 尚无正式 tag，可先用 @main
uv tool install git+https://github.com/hyde-zhao/meta-flow@v1.0.0
mf --version
```

- 用户不需要 clone 源码；`uv tool install` 负责拉取、构建、安装 CLI。
- 维护者从源码安装：

```bash
git clone https://github.com/hyde-zhao/meta-flow
cd meta-flow
uv sync
uv run mf --version
```

- R0/R1 不发布 PyPI；R2 如确有需要再评估。
- 正式版本使用 Git tag + GitHub Release；SHA256 校验在发布说明中提供。
- 不移植 v0 的 provider receipt / qualification 全套机器。

### 9.2 默认安装 maintainer

```bash
mf setup --platform claude
```

按用户要求，默认安装 `meta-maintainer` 到用户级平台目录（如 `~/.claude/agents/`）。

### 9.3 工作区初始化

```bash
cd ~/work/my-cs-app
mf init --name my-cs-app
```

`mf init` 创建：

- `contracts/` git 仓（含角色文件、project.yaml、roadmap、requirements、standards、state）。
- `deliveries/` git 仓（含角色文件）。
- 根目录 `mf.workspace.yaml`、`CLAUDE.md`、`AGENTS.md`。

之后 manager 在 `contracts/` 与用户对接，规划交付库（frontend/backend）、规范、R1 路标。

### 9.4 安装 worker

```bash
mf worker install --delivery frontend --platform claude
```

写入：

- `deliveries/frontend/CLAUDE.md`（本交付库 worker 约束）。
- `deliveries/frontend/.metaflow/worker.yaml`（delivery id、允许路径、可读契约）。
- 平台角色文件（若需要）。

### 9.5 维护者手动安装

`meta-maintainer` 用于维护 meta-flow 源码本身，**不自动安装**：

```bash
git clone https://github.com/hyde-zhao/meta-flow
cp meta-flow/agents/meta-maintainer.md ~/.claude/agents/
```

维护者职责：拉取源码、跑测试、改 CLI/模板/agent、版本号、CHANGELOG；commit/tag/push 必须用户单独授权。

---

## 10. 规范清单

`contracts/standards/` 下 11 份，每份不超过 2 页：

| 文件 | 内容 |
|---|---|
| `VERSION.md` | R ↔ SemVer 映射、预发布、补丁、外部映射、冻结规则 |
| `REQUIREMENTS.md` | REQ/CHG 字段、优先级、追踪矩阵、基线变更 |
| `PHASE.md` | 五阶段目标、进入/退出、报告模板、用户门禁 |
| `TASK-CARD.md` | 任务卡字段、类型、状态机、并行规则 |
| `ACCEPTANCE.md` | 验收方法、结论枚举、证据绑定、独立性、返工 |
| `DEVELOPMENT.md` | 分支/提交、代码风格、测试要求、禁止越界 |
| `VERIFICATION.md` | 任务自验、manager 验收、阶段验证、回归子集 |
| `BUGS.md` | 缺陷对象、生命周期、验证/修复联动、发布门禁 |
| `KNOWLEDGE.md` | 术语/行为/约定/偏好/复盘、记录时机、注入与总结 |
| `DELIVERY.md` | 发布说明/用户手册结构、发布清单、跨库引用 |
| `DOCUMENTATION.md` | 文档类型、命名、front matter、单一真相源 |

规范由工具提供默认版本，`mf init` 复制到项目；项目可修改，`project.yaml` 记录规范版本。

---

## 11. 路线图

| 路标 | 目标 | 进入条件 | 退出条件 | 非目标 |
|---|---|---|---|---|
| **R0 骨架**（0.x） | 可跑通的最小闭环 | 新仓建立 | 玩具项目完成 P1–P5；`mf doctor` 通过 | 多平台、迁移、并发 |
| **R1 MVP**（1.x） | 真实项目可用 | R0 退出 | 1 个真实项目完成一个版本；10+ 任务卡验收；用户确认 | 多交付库并发、审计增强、DSH/Codex 平台 |
| **R2 规模化**（2.x） | 多模块/多交付库/多 worker | R1 退出 | 2 个项目、3 个模块、2 个交付库、3 个并发 worker | Web UI、SaaS、多租户 |

R0 交付物：

1. 新仓骨架：`pyproject.toml`、`src/meta_flow/`、`tests/`、`agents/`、`templates/`、`standards/`。
2. `mf` CLI 骨架：`init/status/role/doctor`。
3. 三个角色定义：`meta-maintainer.md`、`meta-manager.md`、`meta-worker.md`。
4. 工作区两仓初始化 + 角色路由三层 + PROJECT-PLAN 模板与校验 + BUG/KNOWLEDGE 目录。
5. 玩具项目 E2E：R1 → P1–P5 → 任务卡 → 验收 → release freeze；包含缺陷记录与知识沉淀。
6. CLI 状态机与 schema 测试。

R1 交付物：

1. 完整五阶段、PROJECT-PLAN 规划（过程/过程交付件/最终交付件能力）与阶段报告。
2. 并行 wave、租约、任务包、交接、证据固化。
3. 11 份规范默认版。
4. 真实项目试点。
5. 安装/升级/worker 安装完整流程。
6. 缺陷跟踪、知识沉淀与纠正记录闭环。

R2 交付物：

1. 多交付库独立版本与发布节奏。
2. 多 worker 并发与冲突检测增强。
3. 可选 `meta-designer`、可选 `audit` profile。
4. DSH（DeepSeek Harness）与 Codex 平台适配与对等验证。

---

## 12. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 新系统再次膨胀 | 命令预算 ≤40（核心约 30）；规范 ≤11 份；agent ≤250 行/个；不引入 CP/CR/ledger 全套 |
| manager 验收瓶颈 | WIP 限制；`task graph` 显示 submitted 队列；设计/验证通过任务类型分派 |
| worker 自证自洽 | 验收标准前置；证据绑定；manager 重跑；越界 diff 拒绝；独立 verify/review 任务 |
| 状态并发冲突 | 每任务一文件；`current.json` 派生；lease；追加 ledger |
| 两仓同步复杂 | `mf doctor` 校验；`delivery.yaml` 声明版本与契约；R0/R1 单 deliveries 仓 |
| 平台差异 | R1 只 Claude Code；R2 再支持 DSH/Codex；未测试不宣称对等 |
| 设计工作量压垮 manager | `kind: design` 任务分派；R2 可选 `meta-designer` |
| 强审计行业要求 | 核心保持轻量；R2 可选 `audit` profile |

---

## 13. 待决事项

无。仓库命名/归档、平台支持节奏（R1 Claude；R2 DSH + Codex）、分发方式（Git 安装，不发布 PyPI）、License（MIT）、`mf verify record`（保留）、交付库版本策略（按项目 `version_policy`）均已决定。

---

## 14. 决策记录

| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-11-21 | 产品名保留 Meta Flow；v1 新仓 | 品牌连续；旧仓归档 |
| 2026-11-21 | 三角色：meta-maintainer / meta-manager / meta-worker | 权限边界清晰；manager/worker 成对；maintainer 替代有歧义的 po/operator |
| 2026-11-21 | 版本双轨：R{n} ↔ n.x.y + SemVer | 路标管范围，SemVer 管产物；一一对应可追踪 |
| 2026-11-21 | 两仓：contracts + deliveries | 契约库是公共真相；交付库是完整交付单元 |
| 2026-11-21 | 目录级角色 + hook + CLI 强制 | 平台无原生按目录切 agent；三层等价实现 |
| 2026-11-21 | 设计作为任务类型，不新增角色 | 保持三角色；设计是工作类型，不是权限边界 |
| 2026-11-21 | 并行 wave + 任务包 + 交接固化 | worker 独立上下文；manager 不读交付源码 |
| 2026-11-21 | 最终命名：新仓 `meta-flow`；旧仓 `meta-flow-v0` 归档 | 产品名与仓库一致；旧链接保留归档说明 |
| 2026-11-21 | R1 只支持 Claude Code；R2 支持 DSH + Codex | 先跑通核心，平台适配后置 |
| 2026-11-21 | 不发布 PyPI；用户 Git 安装，维护者源码安装 | 降低分发复杂度；用户无需 clone |
| 2026-11-21 | MIT License | 开源、宽松、简单 |
| 2026-11-21 | 保留 `mf verify record` | 阶段级/端到端证据可查询；发布门可强制 |
| 2026-11-21 | 交付库版本按项目 `version_policy`；meta-flow 自身单一交付 | 通用规则不绑定 meta-flow 自身；R1 默认 same-major |
| 2026-11-21 | manager 在 P1 生成 `PROJECT-PLAN.md` | 明确过程、过程交付件、最终交付件能力 |
