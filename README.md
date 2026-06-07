# Meta Flow 元工作流

> 通用 Agent/Skill 工作流产物工厂 — 从需求到交付的全流程编排。

## 目录结构

| 目录 | 用途 |
|------|------|
| `delivery/` | **meta-flow 自身可独立交付的包**（可推送为独立 Git 仓库）；外部 production 项目的交付出口需按目标 README/docs 或用户确认路由 |
| `delivery/agents/` | 交付 Agent 定义（安装脚本从此读取，`<name>.md`） |
| `delivery/skills/` | 交付 Skill 定义（结构为 `<name>/SKILL.md`；模板位于 `<name>/templates/`） |
| `delivery/rules/` | 平台规则文件（`AGENTS.md`、`CLAUDE.md`） |
| `delivery/scripts/` | 安装脚本入口（`install.py` / `install.sh` / `install.ps1`）；需随 Skill 一起安装的私有脚本应放在对应 `delivery/skills/<skill>/scripts/` 下 |
| `scripts/` | 仓库级检查/构建脚本（不随 `delivery/` 一起安装到目标平台） |
| `.agents/agents/` | 元工作流引擎 Agent 定义（不参与安装） |
| `.agents/skills/` | 元工作流引擎 Skill 定义（不参与安装） |
| `.input/` | 只读输入目录（用户提供的原始材料） |
| `~/.meta-flow/` | 安装器状态目录（仅保存安装 manifest，不作为当前元工作流运行态输出目录） |
| `docs/` | 长期产品、设计、质量和发布文档（生产项目按目标 README/docs 约定或用户确认路由） |
| `docs/product/` | 场景、需求、测试矩阵、Story Map、MVP 范围、发布切片和 backlog |
| `docs/design/` | 蓝图、领域图、依赖图、HLD 和架构决策 |
| `docs/features/` | Feature 级 DESIGN.md / TEST-PLAN.md / TASKS.md |
| `docs/quality/` | 测试策略、测试报告、质量评审和修复摘要 |
| `docs/release/` | 发布说明、部署检查、回滚、迁移和反馈入口 |
| `process/` | 运行时文档（gitignored，STATE.md / REQUEST.md / plans / stories / CR / discussions / checks 等） |
| `process/discussions/` | CP2 / CP3 讨论日志（gitignored，用于人类审计和中断恢复，不替代正式产物） |
| `process/checks/` | 自动检查点结果（gitignored，CP0-CP8 自检证据） |
| `process/context/` | 阶段上下文胶囊（gitignored，CP2/CP3/CP5/CP6/CP7/CP8 的默认读取入口，用于减少子 agent token 消耗） |
| `process/checkpoints/` | 人工检查点审查稿（gitignored，CP2/CP3/CP5/CP8 Decision Brief、checklist 与审查结果；CP4 仅自动预检） |

## 输出隔离原则

所有由元工作流产生的文件统一按层输出。meta-flow 自身改进使用当前仓库 `delivery/`；外部 production 项目必须先读取目标 `README.md` / `README.*` / `docs/` 的交付约定，若无约定则先给出建议并等待用户确认。

分层原则：

- `docs/` 承载长期可交付文档：蓝图、HLD、Feature 设计、场景/需求、质量报告和发布资料。
- `process/` 承载运行过程文档：状态、计划、Story 执行态、讨论日志、handoff、CR、自动检查结果。
- `process/context/` 承载阶段上下文胶囊：下游 Agent、人工门禁、验证和发布准备默认先读 capsule；只有缺失、冲突、字段不足、人工审计或深度评审时才展开读取完整正式文档。
- `process/checkpoints/` 承载人工确认态：CP2 / CP3 / CP5 / CP8 Decision Brief、checklist 和人工审查结果。
- 旧项目中的 `process/USE-CASES.md`、`process/HLD.md`、根目录 `checkpoints/CP*.md` 等只作为 legacy fallback 读取；新生成默认写入 `docs/...` 和 `process/checkpoints/...`。

核心长期产物的 canonical 路径包括：`docs/product/SCENARIOS.yaml`、`docs/product/MVP-SCOPE.md`、`docs/design/BLUEPRINT.md`、`docs/release/DEPLOY-CHECKLIST.md`。

```
├── process/                     # 运行时文档（默认建议 gitignore）
│   ├── STATE.md
│   ├── REQUEST.md
│   ├── INPUT-INDEX.md
│   ├── CLARIFICATION-LOG.md
│   ├── STORY-BACKLOG.md
│   ├── DEVELOPMENT-PLAN.yaml
│   ├── discussions/
│   ├── checks/
│   ├── context/
│   ├── checkpoints/
│   ├── changes/
│   └── stories/                  # Story 卡片、LLD 和 Story 级 IMPLEMENTATION.md
├── docs/                        # 长期可交付文档（production 项目可按目标约定改路由）
│   ├── product/
│   │   ├── USE-CASES.md
│   │   ├── REQUIREMENTS.md
│   │   ├── SCENARIOS.yaml
│   │   ├── TEST-MATRIX.md
│   │   ├── STORY-MAP.md
│   │   ├── MVP-SCOPE.md
│   │   ├── RELEASE-SLICES.md
│   │   └── BACKLOG.md
│   ├── design/
│   │   ├── BLUEPRINT.md
│   │   ├── DOMAIN-MAP.md
│   │   ├── DEPENDENCY-MAP.md
│   │   ├── HLD.md
│   │   └── ARCHITECTURE-DECISION.md
│   ├── features/<feature>/
│   │   ├── DESIGN.md
│   │   ├── TEST-PLAN.md
│   │   ├── TASKS.md
│   │   └── IMPLEMENTATION.md     # 复杂 / 高风险 Feature 的实现执行证据
│   ├── quality/
│   │   ├── TEST-STRATEGY.md
│   │   ├── VERIFICATION-REPORT.md
│   │   ├── TEST-REPORT.md
│   │   ├── REVIEW.md
│   │   └── FIXES.md
│   └── release/
│       ├── RELEASE-NOTES.md
│       ├── DEPLOY-CHECKLIST.md
│       ├── ROLLBACK.md
│       ├── MIGRATION.md
│       └── FEEDBACK.md
├── process/
│   └── release/
│       └── RELEASE-CONTEXT.yaml
└── delivery/                    # meta-flow 自身最终交付物（production 项目不默认使用）
    ├── README.md
    ├── doc/
    ├── agents/
    ├── skills/
    ├── rules/
    └── scripts/
```

安装测试优先使用全局命令或 `uv run`：

```bash
meta-flow install codex --scope project --component full --dry-run
uv run --python 3.11 python delivery/scripts/install.py codex --dry-run
```

## `~/.meta-flow` 目录说明

`~/.meta-flow/` 当前不承载 Meta Flow 的运行态文档，也不是 `process/`、`process/checks/`、`process/checkpoints/` 或交付出口的替代目录。当前规则要求元工作流运行态仍写入仓库根目录下的 `process/`、自动检查结果写入 `process/checks/`、人工审查稿写入 `process/checkpoints/`；交付态按 engagement mode 路由，meta-flow 自身改进写当前仓库 `delivery/`，外部 production 项目按目标项目约定或用户确认输出。

当前实现中，`delivery/scripts/install.py` 会把安装状态写入 `~/.meta-flow/delivery/doc/INSTALL-MANIFEST.yaml`。该 manifest 记录已安装的平台、scope、安装时间、canonical commit、目标路径和卸载所需的 remove path。`meta-flow uninstall <platform>` 与 `delivery/scripts/install.py uninstall <platform>` 依赖这个文件精确卸载。

因此：

1. 若仍需要通过安装器执行精确卸载，应保留 `~/.meta-flow/`。
2. 若确认不再需要历史安装记录或安装器卸载能力，可以删除 `~/.meta-flow/`，但会丢失既有安装记录。
3. `~/.meta-flow/` 位于用户主目录，不属于当前仓库跟踪范围；不应作为项目运行态文档或交付出口使用。

## Python 环境规范（uv）

当前仓库对 Python 运行环境采用 `uv` 作为统一工具链，并已提供 `pyproject.toml` / `uv.lock` 与 `meta-flow` console script。因此本阶段的执行约束是：

1. 使用 `uv` 安装和选择 Python 解释器，不以系统 Python 作为默认入口。
2. 运行仓库内 Python 脚本时，优先使用 `uv run --python <version> python <script>`；安装入口优先使用 `meta-flow install`。
3. 一次性工具与临时依赖优先使用 `uvx` 或 `uv run --with <package>`，不把裸 `pip install` 作为日常流程。
4. 安装到目标项目的 uv 规范统一通过 `delivery/rules/AGENTS.md`、`delivery/rules/CLAUDE.md` 传播。

示例：

```bash
uv python install 3.11
uv tool install --editable .
meta-flow install codex --scope user --component rules
meta-flow install codex --scope project --component full --project-dir /path/to/project
meta-flow uninstall codex --scope project --project-dir /path/to/project
meta-flow install codex --help
meta-flow uninstall codex --help
# 从项目根运行
uv run --python 3.11 python delivery/scripts/install.py claude --dry-run
# 或从 delivery/ 目录运行（delivery 作为独立仓库时）
cd delivery && uv run --python 3.11 python scripts/install.py claude --dry-run
```

## 开发节奏

1. `meta-po` 初始化请求并写入 CP0 自动检查结果。
2. `meta-po` 将需求澄清阶段委托给 `meta-pm`。用户直接与 `meta-pm` 通过 Scenario Gray Areas 识别 3-4 个会影响交付的场景灰区，选择 1-3 个重点讨论；未选项进入 Deferred Ideas。随后输出场景 / 需求，写入 CP1 / CP2 自动检查结果；用户确认“可提交给 meta-po 汇总”后交还，meta-po 生成 `process/context/CP2-REQUIREMENT-CONTEXT.yaml` 并发起 CP2 Decision Brief。
3. CP2 通过后，`meta-po` 将 HLD 设计阶段委托给 `meta-se`。用户直接与 `meta-se` 讨论 Architecture Gray Areas 和 advisor table，并使用 `Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch` 表格形成方案输入；随后 `meta-se` 输出含适用性矩阵、Use Case → Architecture Traceability 和场景模拟的 `HLD.md`。用户确认“HLD 草案可提交给 meta-po 发起 CP3”后交还，meta-po 生成 `process/context/CP3-DESIGN-CONTEXT.yaml` 并发起 CP3。
4. `meta-se` 写入 CP4 自动预检；CP4 不再单独人工确认，结果汇入 CP5 批量 LLD 决策摘要。
5. CP3 通过后，`meta-se` 先生成 `docs/design/FEATURE-DESIGN-MATRIX.md`，判定哪些 Feature 需要 `docs/features/<feature>/DESIGN.md` / `TEST-PLAN.md` / `TASKS.md`，并为每个 Story 标记 `feature_design_refs` 与 `lld_policy=full-lld|technical-note|waived`。
6. `meta-dev` 并行输出全部目标 Story 的设计证据和 CP5 自动预检：高风险 Story 输出完整 LLD，低风险 Story 在 Story 卡片中补 `## 技术说明`，明确豁免的 Story 写 waived 证据。遇到实现灰区时只写 `STATE.md.parallel_execution.lld_clarification_queue`。`meta-po` 作为 question broker 合并问题、批量询问用户、回填答案，然后生成 `process/context/CP5-LLD-CONTEXT.yaml` 和 `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md`，一次性确认全部设计证据、CP4 摘要、clarification 队列、依赖门控和文件所有权。
7. 全量 CP5 确认且 `dev_gate` 满足后，`meta-po` 按 Wave / Story DAG 自动调度 `meta-dev` 并记录证据；交接前生成或更新 `process/context/CP6-IMPLEMENTATION-CONTEXT.yaml`。`meta-dev` 使用 `implementation-execution` 产出实现对象清单、设计契约映射、测试 / Fixture 计划、最小实现切片、平台差异和交接摘要。复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / 护栏 / 平台适配 / 发布相关 Story 写完整 `IMPLEMENTATION.md`，低风险 Story 可写 Story 摘要或 DEV-LOG；实现完成后写入 CP6 编码完成结果。
8. Story CP6 通过后，`meta-po` 自动调度 `meta-qa` 并记录证据；交接前生成或更新 `process/context/CP7-VERIFICATION-CONTEXT.yaml`。`meta-qa` 使用 `verification-execution` 消费 CP6 实现执行证据、设计证据和 `TEST-MATRIX.md` 摘要，输出验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、问题和剩余风险，再用 `quality-review` 固化 TEST-REPORT / REVIEW / FIXES 并写入 CP7。CP7 结论为 `PASS` / `WAIVED` 时进入 verified，`PASS_WITH_RISK` 时可推进但风险进入 CP8，`NEEDS_REWORK` 回 meta-dev，`NEEDS_DESIGN_CLARIFICATION` 回 meta-se / meta-po，`BLOCKED` 阻断。
9. 所有目标 Story 验证后，`meta-po` 自动调度 `meta-doc` 完成文档，`meta-qa` 使用 `release-readiness` 先生成 `process/release/RELEASE-CONTEXT.yaml` 和 `process/context/CP8-DELIVERY-CONTEXT.yaml`，再按 `release_artifact_profile=minimal|compact|full` 裁剪发布文档并写入 CP8 自动预检。CP8 的 `release_decision=READY|READY_WITH_RISK` 才可发起人工终验，`NOT_READY` 阻断，`RELEASED|FAILED` 必须有独立真实发布授权；CP8 Decision Brief 人工终验通过后进入 delivered。

## 检查点

Meta Flow 默认采用 CP0-CP8 检查点。所有检查点都包含 Entry Criteria、Checklist、Exit Criteria、Deliverables。

| CP | 名称 | 类型 | 文件 |
|----|------|------|------|
| CP0 | 原始请求受理门 | 自动 | `process/checks/CP0-REQUEST-INTAKE.md` |
| CP1 | 用户场景完备门 | 自动 | `process/checks/CP1-USE-CASE-COMPLETENESS.md` |
| CP2 | 需求 / 场景 / 范围基线门 | 自动预检 + 人工 | `process/checks/CP2-REQUIREMENTS-BASELINE.md`；`process/checkpoints/CP2-REQUIREMENTS-BASELINE.md` |
| CP3 | 蓝图 / HLD 架构评审门 | 自动预检 + 人工 | `process/checks/CP3-HLD-CONSISTENCY.md`；`process/checkpoints/CP3-HLD-REVIEW.md` |
| CP4 | Story 拆解与并行安全门 | 自动预检（汇入 CP5） | `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md` |
| CP5 | Story 设计证据可实现性门 | 全量自动预检 + 全量人工 | `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md`；`process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` |
| CP6 | Story 编码完成门 | 滚动自动；检查实现执行证据 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md` |
| CP7 | Story 验证完成门 | 滚动自动；检查验证执行证据和结论分级 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md` |
| CP8 | 交付就绪门 | 自动预检 + 人工 | `process/checks/CP8-DELIVERY-READINESS.md`；`process/checkpoints/CP8-DELIVERY-READINESS.md` |

关键人工检查点由 `meta-po` 发起。CP2 / CP3 / CP5 / CP8 发起前会生成 Context Capsule、Decision Brief 和待人工决策清单，并提示 `process/checkpoints/CP*.md` 路径。待人工决策清单的状态机对象是 `STATE.md.human_gate_decisions.pending_human_decisions[]`，会逐项列出决策 ID、决策类型、待确认问题、推荐方案、至少 1 个备选方案（优先 2 个）、优劣分析、影响 / 风险和回退 / 切换条件。用户审查后可以在文件的“人工审查结果”中填写结论，也可以在对话中回复 `approve`、`修改: <具体修改点>`、`reject`，由 `meta-po` 回填结果文件；`approve` 表示接受清单内全部推荐方案。CP4 只写自动预检并汇入 CP5。

发起人工门禁的对话本身也受校验：必须包含 checklist 路径、自动预检结论、Context Capsule 摘要、决策收集覆盖摘要、待决策项数量、待决策表格或压缩后的 blocking / high-risk 决策摘要和三个 exact 回复。checkpoint 文件中的 Decision Brief 始终完整；对话可按 `decision_brief_profile=full|compact|summary` 压缩。真实运行、凭据、安全、外部接口、数据写入、publish、live / 交易类事项必须独立列为不授权项；`approve` 不代表授权这些操作。CP8 还必须输出 follow-up tracking 分流：关闭范围、不授权范围、风险接受项、后续 CR 候选项、取消 / deferred 项。后续 CR 候选只进入 `process/changes/CR-*-FOLLOW-UP-TRACKING-YYYY-MM-DD.md` 台账，用户决定推进某项时才创建正式 CR。

启动台账中的后续 CR 时，直接让 `meta-po` 指定台账和候选编号：

```text
@meta-po 启动后续 CR
台账：process/changes/CR-019-FOLLOW-UP-TRACKING-2026-05-31.md
候选编号：CR-020
目标：推进 Windows gateway 实机部署准入
```

meta-po 必须先读取台账、`STATE.md.active_change`、`STATE.md.cr_tracking`、`process/changes/CR-INDEX.yaml`（若存在）和当前活跃 `process/changes/CR-*.md`，执行 CR 冲突预检。`candidate` / `spike_candidate` 只是 backlog，不占执行锁；转为正式 CR 后才把台账状态、`STATE.md.cr_tracking` 和 `CR-INDEX.yaml` 改为 `active`，写入正式 CR 路径并设置活跃变更。若已有未完成 CR，新 CR 与其影响同一正式文档、Story、文件 owner、外部接口、安全 / 运行授权或风险接受项，默认不得并行推进；meta-po 必须给出合并到现有 CR、保持候选等待、标记 `blocked`、拆分无冲突子集或 `superseded` 的决策表，由用户确认后再继续。

询问“当前状态”或“还有哪些 CR 需要推进”时，meta-po 必须输出 CR 盘点视图：`active formal CR`、`blocked formal CR`、`follow-up candidate`、`spike_candidate`、`stale_status_conflicts`。如果当前项目存在 `scripts/check_cr_tracking_consistency.py`，状态盘点、候选 CR 启动、CR 关闭和 CP8 follow-up 分流后都应运行：

```bash
uv run --python 3.11 python scripts/check_cr_tracking_consistency.py --project-root .
```

该脚本用于发现 `STATE.md.active_change` 指向已关闭 CR、多个 active CR 未授权、follow-up candidate 已有正式 CR 文件、台账 active 项缺正式 CR 路径等问题。

CP2 会额外检查 `process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md` 和 `process/checks/CP2-DISCUSSION-CHECKPOINT.json`，用于追溯 Scenario Gray Areas、用户选择、freeform 确认和 Deferred Ideas。CP3 会额外检查 `process/discussions/CP3-HLD-DISCUSSION-LOG.md` 和 `process/checks/CP3-DISCUSSION-CHECKPOINT.json`，用于追溯 Architecture Gray Areas、advisor table、方案形成输入、核心 ADR 早确认、HLD 后审查意见和切换条件。Discussion Log 用于审计和恢复，不作为默认下游输入；下游先消费 `process/context/*-CONTEXT.yaml`，必要时再读取 `USE-CASES.md`、`REQUIREMENTS.md`、`SCENARIOS.yaml`、`TEST-MATRIX.md`、`STORY-MAP.md`、`MVP-SCOPE.md`、`BLUEPRINT.md`、`DOMAIN-MAP.md`、`DEPENDENCY-MAP.md`、`HLD.md`、`ARCHITECTURE-DECISION.md`、`FEATURE-DESIGN-MATRIX.md` 或 Decision Brief。

异步 power mode（例如 `process/discussions/CP2-QUESTIONS.json/html` 或 `CP3-QUESTIONS.json/html`）是后续可选增强，本轮不作为默认产物或验收前置。

CP6 / CP7 还必须包含 `Agent Dispatch Evidence` 小节。`process/handoffs/*.md` 只表示交接，不表示子 agent 已执行；Story 编码或验证完成必须有 `spawn_agent` / `resume_agent` / `send_input`、平台 Task/Subagent 返回标识，并在 `STATE.md.agent_lifecycle` 或 handoff `dispatch` 中记录 `agent_id` 或 `thread_id`，或用户明确批准的 `inline-fallback`。CP6 必须额外记录实现执行证据路径、证据类型和 N/A 理由；CP7 必须记录验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、问题和剩余风险、阶段决策；缺少调度证据或必需实现 / 验证证据时，CP6 / CP7 只能判定为 `FAIL` 或 `BLOCKED`。

用户启动正式工作流后，同工作流内默认允许 `meta-po` 自动拉起所需功能 Agent。该授权只覆盖真实子 agent 调度；平台无法拉起子 agent 或需要 inline fallback 时，仍必须单独询问用户。

## 阶段委托与 LLD Clarification Queue

`STATE.md.delegated_interaction` 记录当前阶段委托：`phase`、`agent_role`、`agent_id/thread_id`、`handoff_path`、`status`、`started_at`、`returned_at` 和 `return_summary_path`。委托只表示阶段内交互权移交，不表示 CP2 / CP3 已确认。`meta-pm` / `meta-se` 可直接与用户讨论本阶段草案；正式人工门仍由 `meta-po` 发起。

`STATE.md.parallel_execution.lld_clarification_queue` 记录并行 LLD 阶段的实现灰区。每个 item 至少包含 `id/story_id/owner_agent/question/options/recommendation/pros_cons/impact_surface/blocks_lld/answer/status`，其中 `options` 必须能表达 1 个推荐方案和至少 1 个备选方案。多个 `meta-dev` 不直接并发问用户；`meta-po` 合并同类问题后一次性询问用户，并把答案回填到 queue、LLD 和 DEV-LOG。存在未回答 `blocks_lld=true` 项时不得发起 CP5；转 OPEN / Spike 的项必须在 CP5 Decision Brief 中暴露。

## fast-lane 快速模式

`fast-lane` 用于低风险轻量实现、小型 Skill / Agent / rules 修订和文档更新。它减少需求 / HLD / LLD / IMPLEMENTATION / VERIFICATION 文档厚度和人工门数量，但不跳过追溯证据。

适用条件：

- 不改变架构、安装路径、权限边界、安全规则或外部接口契约
- 不涉及多个 Story、文件所有权冲突、运行时依赖或不可逆迁移
- 可以用一页 `Intent + Approach Brief` 解释范围、做法、验证和风险

不适用时自动升级 `standard`。fast-lane 仍必须保留 `REQUEST.md`、`STATE.md`、必要变更记录、CP6 / CP7、Agent Dispatch Evidence、实现执行证据摘要、验证执行证据摘要、`process/release/RELEASE-CONTEXT.yaml` 和 CP8 终验摘要；发布阶段默认使用 `release_artifact_profile=minimal`，不生成完整 release 长文档，除非用户明确要求或触发安装 / 权限 / 迁移 / 外部接口风险。

CP2 / CP3 的讨论增强不会强行把所有小修改升级为 standard；只有出现架构、权限、安全、平台安装、外部接口、文件所有权冲突或多 Story 依赖等条件时才升级。fast-lane 下若 discussion log / checkpoint 不适用，自动检查必须写明 N/A 原因。

## 交付目录约定

安装脚本从 `delivery/` 内读取交付件，推荐使用 `meta-flow install`：

```bash
# user scope 默认只安装 rules
meta-flow install codex --scope user

# project scope 默认安装 full 组件（rules + agents + skills）
meta-flow install codex --scope project --project-dir /path/to/project

# 未指定 --project-dir 时，交互式终端会提示确认当前目录或输入其他目录
meta-flow install codex --scope project

# 显式安装完整组件
meta-flow install codex --scope project --component full --project-dir /path/to/project

# 卸载安装记录中的组件，默认卸载 full
meta-flow uninstall codex --scope project --project-dir /path/to/project
meta-flow uninstall codex --scope project --component rules --project-dir /path/to/project
```

兼容运行方式：

```bash
# 从项目根目录运行
uv run --python 3.11 python delivery/scripts/install.py claude

# 以 delivery/ 为根（独立 Git 仓库）运行
cd delivery
uv run --python 3.11 python scripts/install.py claude
```

交付目录结构：
- `delivery/agents/` — canonical Agent 定义
- `delivery/skills/` — canonical Skill 定义（含 `<skill>/templates/`、`<skill>/scripts/` 等私有运行时资产）
- `delivery/rules/` — 平台规则文件
- `delivery/doc/PLATFORM-CONTRACTS.yaml` — 平台安装路径单一真相源，安装器、DryRun 与 guardrail 共同读取

组件语义：

- `rules`：只安装平台规则入口（如 `AGENTS.md` / `CLAUDE.md`）
- `agent`：安装 agents + skills
- `full`：同时安装 rules 与 agent 组件
- `meta-flow uninstall <platform>` 未指定 `--component` 时默认卸载 `full`；可用 `--component rules|agent|full` 精确卸载组件
- legacy `--content all|agents|skills|rules` 仅保留兼容，新文档优先使用 `--component`

Agent 命令与显示区分：

| canonical role | Codex 命令 / nickname_candidates | Claude Code color |
|---|---|---|
| `meta-po` | `po-zhao`、`po-qian`、`po-sun`、`po-li`、`po-zhou` | `red` |
| `meta-pm` | `pm-wu`、`pm-zheng`、`pm-wang`、`pm-feng`、`pm-chen` | `orange` |
| `meta-se` | `se-chu`、`se-wei`、`se-jiang`、`se-shen`、`se-han` | `yellow` |
| `meta-dev` | `dev-yang`、`dev-zhu`、`dev-qin`、`dev-you`、`dev-xu`、`dev-he`、`dev-lv`、`dev-shi`、`dev-zhang`、`dev-kong` | `green` |
| `meta-qa` | `qa-he`、`qa-lv`、`qa-shi`、`qa-zhang`、`qa-kong`、`qa-cao`、`qa-yan`、`qa-hua`、`qa-jin`、`qa-wei` | `cyan` |
| `meta-doc` | `doc-cao`、`doc-yan`、`doc-hua`、`doc-jin`、`doc-wei` | `purple` |

canonical role 名称仍为 `meta-*`，用于状态机、handoff 和检查点审计。Codex 安装器把上表命令写入 `.codex/agents/*.toml` 的 `nickname_candidates`；Claude Code 文件型 subagent 不支持 nickname，安装器使用 `color` 字段在任务列表和 transcript 中区分角色。

## 交付护栏

1. `delivery/scripts/` **只允许**安装器入口：`install.py`、`install.sh`、`install.ps1`。
2. 任何被 active Skill 运行时使用的模板、脚本、schema、示例，都必须放在 `delivery/skills/<skill>/` 私有子目录下。
3. active Skill 的 `SKILL.md` 不得引用 `delivery/scripts/*.py`，也不得使用依赖当前工作目录的 `python scripts/...` 写法。
4. Python 缓存/编译产物（`__pycache__/`、`*.pyc`）不得入库。
5. Codex Skill 禁止安装到 `.codex/skills` 或 `~/.codex/skills`；项目级使用 `.agents/skills`，用户级使用 `~/.agents/skills`。
6. 安装器必须在写入前检查路径组件冲突；例如目标 `.codex` 已是普通文件时，应明确报错 `安装路径被非目录占用`，不得输出 Python traceback。

meta-flow 自身仓库级静态检查命令：

```bash
uv run --python 3.11 python scripts/check_delivery_guardrails.py
```

该脚本不属于外部 production 项目的默认交付物。仅当当前仓库存在 `scripts/check_delivery_guardrails.py` 时才运行上述命令。若在其他项目使用 meta-flow 生成或安装工作流，而目标项目没有该脚本，外部 production 项目不得硬引用 `/home/hyde/projects/meta-flow/scripts/check_delivery_guardrails.py`；应按目标项目 README/docs 中的测试、构建、安装 dry-run 或用户确认的验证命令执行。

命名规则：

- Claude Code / OpenClaw 的 Agent 文件后缀保持为 `.md`
- Codex 目标会自动转换为 `.toml`

## 快速使用 meta-flow

首次启动一个正式交付工作流时，建议直接给出目标、平台和约束：

```text
@meta-po 开始
目标：为 <agent / skill / workflow 名称> 产出正式方案
平台：Claude Code、Codex
要求：先澄清需求，再给我 HLD，确认后再拆 Story
```

常用控制语句：

```text
@meta-po 当前状态
@meta-po 下一步
@meta-po 继续
@meta-po 快速修改
```

CLI 也提供只读辅助入口：

```bash
meta-flow status
meta-flow next
meta-flow doctor
```

如果当前是在优化 meta-flow 本身，而不是为目标产物交付方案，请显式声明：

```text
当前是在做 meta 工作流优化，请进入 meta-self-dev 模式。
```

详细使用说明见 [delivery/README.md](delivery/README.md) 和 [delivery/doc/USER-MANUAL.md](delivery/doc/USER-MANUAL.md)。
