---
status: draft
version: "1.1"
confirmed_by: ""
confirmed_at: ""
engagement_mode: meta-self-dev
scenario_subject_type: implementation-carrier
scenario_subject_id: "meta-flow"
target_artifact_type: workflow
governance_mode: review-gated
review_policy: strict
total_use_cases: 4
---

# USE-CASES：meta-flow 当前项目追溯补录

> 本文件根据当前仓库已存在的 HLD、Story、交付文档和规则追溯补录，描述 **meta-flow 作为元工作流实现载体** 的核心使用场景。

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 | 文档处理方式 |
|---|---|---|---|---|
| 1.0 | 2026-04-23 | meta-pm | 追溯补录 meta-flow 当前项目场景基线，形成 UC-01 至 UC-04。 | 初始化基线 |
| 1.1 | 2026-04-29 | meta-po | CR-003：追加需求 / 场景变更追溯规则的修订记录，不改动 v1.0 场景正文。 | 原文档更新；保留既有基线并追加治理记录 |

## 用户画像（Personas）

| 画像 ID | 角色名称 | 典型背景 | 核心诉求 | 技术水平 |
|---|---|---|---|---|
| P-01 | 元工作流维护者 | 持续维护本仓库的 Agent、Skill、规则和过程文档，希望 workflow 可长期演进且不失控。 | 让 meta 工作流的结构、契约、提示词和交付包保持一致。 | 高级 |
| P-02 | 平台集成与发布维护者 | 负责将 workflow 产物安装到 Copilot / Claude Code / Codex / OpenClaw，并检查平台差异。 | 确保交付目录、安装路径和运行时资产在各平台上都可用。 | 中高级 |
| P-03 | 质量与治理维护者 | 关注 guardrail、评审门禁、命名规则和过程一致性。 | 在不破坏主流程的前提下发现并纠正仓库中的结构漂移。 | 高级 |

## 成功指标（Success Metrics）

| 指标 ID | 指标名称 | 度量方式 | 目标值 |
|---|---|---|---|
| SM-01 | 工作流阶段闭环 | `process/` 中关键阶段文档齐备，阶段间契约文件不缺失 | 关键运行文档缺失数 = 0 |
| SM-02 | 跨平台可交付性 | `delivery/` 产物可被安装脚本按平台复制到目标目录 | 支持 4 个目标平台 |
| SM-03 | 契约一致性 | Story / LLD / Agent / Skill / rules 中的路径、命名、模式字段无双轨 | 关键契约冲突数 = 0 |
| SM-04 | 护栏有效性 | guardrail 扫描可发现资产归属、脚本路径、缓存文件等结构问题 | 静态扫描阻断明显违规项 |

## 明确排除（Out of Scope）

- 使用当前仓库直接实现某个业务领域产品，而不修改 meta 工作流本身
- 运行时托管外部服务、数据库或在线编排控制台
- 脱离 `process/` / `checkpoints/` / `delivery/` 分层约束的临时流程

## 治理附录（Governance）

| 字段 | 当前值 | 说明 |
|---|---|---|
| `engagement_mode` | `meta-self-dev` | 当前工作不是面向外部目标产物的生产交付，而是在优化 meta 工作流实现载体本身 |
| `scenario_subject_type` | `implementation-carrier` | 当前场景主体是本仓库 `meta-flow`，而不是某个外部 Agent / Skill / Workflow |
| `scenario_subject_id` | `meta-flow` | 当前场景真正服务的对象 ID |
| `target_artifact_type` | `workflow` | 当前项目的主要交付对象是一个可安装、可演进的元工作流 |
| `governance_mode` | `review-gated` | 关键设计对象和阶段出口需要评审 / 检查点收敛 |
| `review_policy` | `strict` | 对契约、命名、安装性和边界控制采用严格治理策略 |

## 使用场景列表

### UC-01：维护者收敛和升级元工作流契约

| 字段 | 内容 |
|---|---|
| **使用角色** | 元工作流维护者 |
| **触发条件** | 需要新增或修订模式规则、阶段契约、Story / LLD 命名、Skill 输出规范或 Agent 协作边界 |
| **输入** | 当前仓库中的 `HLD.md`、`ARCHITECTURE-DECISION.md`、`STORY-BACKLOG.md`、规则文件、已有 Story / LLD 文档和用户决策 |
| **处理逻辑** | Given 当前仓库已有运行中的 meta 工作流；When 维护者发起结构性调整；Then workflow 先定位受影响的 Skill / Agent / rule / template，再统一回写正式契约文件，避免一处更新、多处滞后 |
| **输出/结果** | 更新后的 Skill、Agent、rules、模板与过程文档；必要时形成新的 Story / LLD / 变更记录 |
| **前置条件** | 关键设计文档和当前运行态文件可读取，且修改目标属于 meta-flow 自身 |
| **排除情况** | 直接为外部业务仓库产出需求、设计或实现文件，不属于当前场景 |

**处理流程（文字描述）：**
1. 读取现有 HLD、Story、rules 和交付文档，定位当前契约缺口。
2. 判断影响范围属于 Skill、Agent、模板、安装脚本还是过程文档。
3. 按单一契约源回写相关对象，并保持 `.agents/`、`delivery/`、`.github/` 口径一致。

---

### UC-02：发布维护者生成并安装跨平台交付包

| 字段 | 内容 |
|---|---|
| **使用角色** | 平台集成与发布维护者 |
| **触发条件** | 需要将当前 workflow 交付到 GitHub Copilot、Claude Code、Codex 或 OpenClaw，或验证目标目录是否符合平台规范 |
| **输入** | `delivery/` 目录、平台规则文件、`PLATFORM-INSTALL-SPEC.md`、安装脚本参数（platform / scope / content / dry-run） |
| **处理逻辑** | Given 交付资产已存在；When 维护者执行安装或 DryRun；Then workflow 按平台结构复制 Agent、Skill、rules 和脚本入口，并在需要时输出安装清单或结构校验结果 |
| **输出/结果** | 安装后的平台目录、DryRun 结果、安装清单或卸载结果 |
| **前置条件** | `delivery/` 交付树完整，安装脚本入口存在，目标平台和 scope 已明确 |
| **排除情况** | 将 Skill 私有脚本直接暴露为公共 `delivery/scripts/*.py`，或绕过平台目录规范手工拷贝 |

**处理流程（文字描述）：**
1. 根据目标平台和 scope 选择安装路径与内容范围。
2. 使用安装脚本执行 DryRun、正式安装或卸载。
3. 核对目标目录中的 Agent、Skill、rules 与私有资产是否完整可读。

---

### UC-03：维护者按 Story + LLD 增量演进 workflow

| 字段 | 内容 |
|---|---|
| **使用角色** | 元工作流维护者 |
| **触发条件** | 某个已批准 Story 需要进入 LLD、实现、验证或文档化阶段 |
| **输入** | `process/stories/STORY-*.md`、对应 `STORY-*-LLD.md`、`DEVELOPMENT-PLAN.yaml`、`TEST-STRATEGY.md`、平台规则和交付文件 |
| **处理逻辑** | Given Story 已纳入正式 backlog；When 维护者推进某个 Story；Then workflow 按 LLD 起草 → LLD 确认 → 实现 → 验证 的顺序推进，并通过 Story / LLD 文件显式交接上下文 |
| **输出/结果** | 带 `story_slug` 的 Story 卡片、LLD 文档、实现产物、验证报告与状态更新 |
| **前置条件** | HLD 已确认，Story 已批准，依赖 Story 与关键输入可读取 |
| **排除情况** | 跳过 LLD 直接实现，或在 Story / LLD 未确认时越级推进 |

**处理流程（文字描述）：**
1. 从 Story 卡片读取范围、验收标准和 `story_slug`。
2. 先产出并确认对应 LLD，再按 TASK-ID 实现和验证。
3. 回写 Story 状态、日志和交付资产，进入下一个 Wave 或阶段。

---

### UC-04：治理维护者扫描并整改仓库漂移问题

| 字段 | 内容 |
|---|---|
| **使用角色** | 质量与治理维护者 |
| **触发条件** | 仓库中出现路径漂移、共享模板归属错误、安装后不可执行、规则与提示词双轨、命名不直观等问题 |
| **输入** | 仓库文件树、guardrail 扫描结果、规则文件、用户反馈、相关 Story / HLD 文档 |
| **处理逻辑** | Given 当前 workflow 需要保持长期可维护；When 维护者执行审计或收到整改反馈；Then workflow 定位违规资产与契约冲突，修正规则、Skill 归属、命名、文档和安装行为，并把新约束写回正式文件 |
| **输出/结果** | 修复后的仓库结构、更新后的规则与文档、可复用的 guardrail 约束 |
| **前置条件** | 能读取当前仓库状态和相关规则；整改对象属于当前 meta 工作流 |
| **排除情况** | 只在会话中口头约定，不把约束落入正式规则或手册 |

**处理流程（文字描述）：**
1. 运行或阅读 guardrail 检查结果，识别实际漂移点。
2. 判断问题属于资产归属、命名契约、安装路径、模式规则还是过程文档缺失。
3. 修复仓库并回写规则、手册和相关 Skill / Agent 契约，防止同类问题再次出现。

<!-- coverage-checklist: begin -->
## 附录：覆盖自检表

> 本附录是正式兼容结构的一部分；用于记录 8 维覆盖状态，但不改变正文必填字段集。

| 维度 ID | 维度名称 | 状态 | 涉及场景 | 备注 |
|---|---|---|---|---|
| D1 | 用户维度 | 已覆盖 | UC-01, UC-02, UC-03, UC-04 | 覆盖维护者、发布维护者、治理维护者三类核心角色 |
| D2 | 任务维度 | 已覆盖 | UC-01, UC-02, UC-03, UC-04 | 覆盖契约升级、安装交付、Story 推进、治理整改 |
| D3 | 动机维度 | 已覆盖 | UC-01, UC-02, UC-03, UC-04 | 体现长期演进、跨平台交付、顺序推进和结构收敛动机 |
| D4 | 时间维度 | 已覆盖 | UC-01, UC-02, UC-03 | 覆盖设计调整前、发布时、Story 生命周期中的时机 |
| D5 | 环境维度 | 已覆盖 | UC-02, UC-03, UC-04 | 涉及多平台安装环境、process/delivery 文档环境和仓库治理环境 |
| D6 | 方式维度 | 已覆盖 | UC-01, UC-02, UC-03, UC-04 | 同时覆盖对话驱动、文件驱动、安装脚本驱动和扫描驱动 |
| D7 | 异常维度 | 已覆盖 | UC-01, UC-02, UC-03, UC-04 | 覆盖契约冲突、安装失败、越级推进、结构漂移等异常 |
| D8 | 集成维度 | 已覆盖 | UC-01, UC-02, UC-03, UC-04 | 涉及 Skill、Agent、rules、install、process 文档间的集成 |
| Dx | 自定义维度（治理收敛） | 已覆盖 | UC-01, UC-04 | 强调本项目对规则固化和防回归的需求 |
<!-- coverage-checklist: end -->
