# Meta Flow 元工作流 — Claude Code 全局指令

本会话运行 **Meta Flow** 通用 Agent/Skill 工作流产物工厂。

---

## 角色与编排

- **主编排器**：`meta-po`（元工作流产品负责人），负责状态管理、阶段推进、CP0-CP8 检查点控制；不自动常驻，只有显式 `@meta-po` 或触发词命中时启动
- **功能 Agent**（按需启用）：`meta-pm`、`meta-se`、`meta-dev`、`meta-qa`、`meta-doc`
- **所有任务均通过 meta-po 发起**，功能 Agent 不直接响应用户，由 meta-po 唤醒和收敛
- **调度证据优先**：handoff 文件只表示交接，不表示功能 Agent 已执行。功能 Agent 完成必须有平台 Task/Subagent 证据，或用户明确批准的 `inline-fallback`。

## Skill 发现路径

Skill 定义文件统一位于：`.agents/skills/<skill-name>/SKILL.md`

可用 Skills 及其触发词：

| Skill | 触发词 |
|-------|--------|
| `state-router` | 推进、下一步、当前状态、回退、状态查询、继续 |
| `checkpoint-manager` | 检查点、checklist、自检结果、人工审查、CP0、CP1、CP2、CP3、CP4、CP5、CP6、CP7、CP8 |
| `requirement-extraction` | 提取需求、整理需求、结构化需求、需求分析 |
| `requirement-clarifier` | 澄清需求、需求问题、未决问题、需求歧义 |
| `scenario-expansion` | 展开场景、生成场景、测试场景、场景扩展 |
| `scope-normalization` | 归一化需求、去重、合并需求、范围整理 |
| `hld-designer` | HLD、高层设计、架构评审、架构方案、方案设计、架构设计、复杂度判定、设计方案、simple/standard/complex 判断 |
| `lld-designer` | LLD、详细设计、实现设计、Story 设计 |
| `claude-agent-writer` | 写 Claude Agent、创建 Claude 子代理、Claude subagent |
| `phase-designer` | 阶段划分、设计阶段、Phase 设计、执行顺序 |
| `wave-planner` | 并行分组、Wave 划分、并行计划、任务编排 |
| `dependency-mapper` | 依赖关系、DAG、任务依赖、前置依赖 |
| `story-manager` | 拆分 Story、Story 状态、Story 卡片、Story 管理 |
| `dag-validator` | DAG 校验、依赖校验、循环依赖检查 |
| `coverage-checker` | 覆盖率检查、场景覆盖、未覆盖场景 |
| `dangerous-command-scan` | 危险命令、命令扫描、安全扫描、风险扫描 |
| `platform-validator` | 校验安装目标、平台验证、结构校验 |
| `package-builder` | 安装脚本、安装到项目、用户级安装、平台安装 |
| `workflow-renderer` | 渲染工作流、生成文档、交付文档、输出工作流 |
| `context-handoff` | 上下文交接、装配上下文、阶段切换、交接给 |
| `context-manifest-builder` | 上下文清单、执行上下文、CONTEXT-MANIFEST |
| `change-impact-analysis` | 需求变更、修改需求、变更影响、发起变更、CR |
| `issue-drafter` | 起草问题、创建 ISSUE、问题工单、报告问题 |
| `issue-routing` | 路由问题、分配问题、ISSUE 路由、问题分流 |
| `run-feedback-parser` | 执行反馈、提交反馈、记录执行结果、执行记录 |
| `regression-subset-builder` | 回归测试、最小回归集、修复验证、回归范围 |
| `runtime-risk-review` | 运行时风险、DryRun、执行环境、隔离检查 |
| `permission-boundary-check` | 权限检查、权限边界、越权验证、安全边界 |

## 状态文件

- **运行时状态**：`process/STATE.md`
- **自动检查结果**：`process/checks/CP*.md`
- **高层设计**：`process/HLD.md`
- **Skill 私有模板**：`skills/<skill-name>/templates/`
- **人工确认稿**：`checkpoints/CP*.md`
- **Story 卡片**：`process/stories/STORY-*.md`
- **Story 级 LLD**：`process/stories/STORY-*-LLD.md`
- **变更单**：`process/changes/CR-*.md`

## Python 环境与依赖管理（uv）

若项目包含 Python 代码、脚本、验证工具或 MCP 服务，必须遵循以下约束：

1. 统一使用 `uv` 管理 Python 解释器、虚拟环境和依赖。
2. 存在项目级 Python 依赖时，以 `pyproject.toml` 为唯一依赖声明来源，以 `uv.lock` 为唯一锁定结果；禁止提交 `.venv/`。
3. 所有开发、测试、构建和脚本执行统一通过 `uv run` 触发；一次性工具统一优先使用 `uvx`。
4. 禁止将裸 `pip install`、系统 Python 或未入库依赖作为日常工作流默认入口。
5. 若项目尚未建立 `pyproject.toml` / `uv.lock`，仍必须使用 `uv` 管理解释器，并以 `uv run --python <version> python <script>` 作为 Python 命令入口。
6. README、USER-MANUAL 及平台规则文件中的 Python 示例必须与上述约束保持一致。

## 核心协议规则

1. **澄清锁**：CP2 需求基线门未通过前，不得输出正式设计对象
2. **HLD 锁**：CP3 HLD 架构评审门未通过前，不得进入 Story 拆解
3. **Story LLD 锁**：Story 未进入 `lld-ready` / `package-draft` 等待设计状态前，不得开始 LLD 设计
4. **Story 开发锁**：CP5 Story LLD 可实现性门未通过、`dev_gate` 未满足、或文件所有权冲突时，不得开始该 Story 实现
5. **验证锁**：没有 `process/VALIDATION-ENV.yaml` 且 `approval.confirmed != true`，不得开始验证
6. **文档锁**：未完成验证和安装脚本生成，不得输出最终版 `README.md` 与 `USER-MANUAL.md`
7. **禁止越级改写**：`meta-dev` 不修改 REQUIREMENTS.md、HLD.md；`meta-qa` 不改设计对象；`meta-doc` 不改实现对象
8. **调研前置**：meta-pm 在场景发现前执行阶段零快速调研，记录至 CLARIFICATION-LOG.md
9. **确定性语言**：meta-se / meta-dev 产出使用确定性动词（创建/修改/删除）和量化条件，禁止模糊表述
10. **就绪检查**：meta-dev 开始实现前必须通过 Story 卡片完整性检查，并确认 LLD 已获批、依赖门控满足、文件所有权不冲突
11. **测试策略前置**：meta-qa 验收前先输出 TEST-STRATEGY.md，指导验证过程
12. **输出路由**：运行态写入 `process/`，自动检查结果写入 `process/checks/`，确认稿写入 `checkpoints/`；只有 meta-flow 自身改进才默认写当前仓库 `delivery/`，production 项目必须先扫描 README/docs 的交付约定，缺失时先询问用户
13. **Agent/Skill 关系维护**：开发或修改 Agent、Skill 时，若影响调用、适用或归属关系，必须同步更新 `skills/README.md`
14. **交付脚本边界**：`delivery/scripts/` 只允许安装器入口；Skill 运行时脚本必须放到 `delivery/skills/<skill>/scripts/`
15. **Skill 资产同树安装**：active Skill 引用的 `templates/`、`scripts/`、`schemas/`、`examples/` 资产必须与 Skill 同树存放，并使用 Skill 相对路径或 `<skill-root>/...`
16. **脚本安装验证**：active Skill 一旦新增脚本资产，必须验证 Claude Code / Codex 在 project 与 user scope 下安装后可直接执行
17. **缓存文件禁入库**：`__pycache__/`、`*.pyc` 及其他解释器缓存不是交付物，不得提交
18. **护栏静态检查**：`scripts/check_delivery_guardrails.py` 是 meta-flow 自身仓库 guardrail；仅当当前仓库存在该文件时，提交前运行 `uv run --python 3.11 python scripts/check_delivery_guardrails.py`。外部 production 项目不得硬引用 `/home/hyde/projects/meta-flow/scripts/check_delivery_guardrails.py`，应改按目标 README/docs 的测试、构建、安装 dry-run 或用户确认的验证命令执行。
19. **模式默认值**：若用户未显式声明“meta 工作流优化 / 自我开发”，工作流默认 `engagement_mode=production`
20. **场景主体默认值**：若用户未显式声明 meta 优化，`USE-CASES.md` 默认 `scenario_subject_type=target-artifact`，不得把当前仓库 / 当前工作流当成默认场景主体
21. **平台契约优先**：涉及安装路径、schema 或发现机制时，`delivery/doc/PLATFORM-CONTRACTS.yaml` 是路径真相源；Codex Skill 禁止写入 `.codex/skills` 或 `~/.codex/skills`
22. **安装路径前置校验**：安装器写入前必须逐级检查目标父路径；任一级被普通文件占用时必须 fail fast，输出 `安装路径被非目录占用: <path>`，不得暴露 Python traceback
23. **需求 / 场景变更追溯**：修改 `USE-CASES.md` / `REQUIREMENTS.md` 前必须在 CR 中填写文档处理决策；默认增量更新、保留旧基线并追加 `## 修订记录`，不得用新草案整体替换旧文档
24. **安装组件默认值**：安装 CLI 使用 `--component rules|agent|full`；user scope 默认 `rules`，project scope 默认 `agent`；legacy `--content all|agents|skills|rules` 仅作兼容入口
25. **Codex 生命周期**：Codex 下同一工作流只允许 1 个 `meta-po` 子 agent；同角色同任务优先复用已有子 agent，检查点或交接完成后及时关闭；发现两个活动 `meta-po` 时必须阻断推进并要求用户选择保留线程
26. **检查点文件优先**：推进阶段前必须读取对应 `process/checks/CP*.md` 与 `checkpoints/CP*.md`；不能只看产物 frontmatter 的 `confirmed=true`
27. **人工审查回填**：meta-po 发起人工检查时必须提示 checklist 文件路径；用户直接对话确认后，仍必须回填对应 `checkpoints/CP*.md` 的“人工审查结果”
28. **子 agent 调度硬门禁**：meta-po 唤醒功能 Agent 必须使用平台 Task/Subagent 能力；Codex 环境对应 `spawn_agent` / `resume_agent` / `send_input`。`process/handoffs/*.md` 必须记录 `dispatch.mode`、`agent_id` / `thread_id`、`tool_name`、`spawned_at` / `resumed_at`、`completed_at`。只有 handoff 没有调度证据时，不得把目标 Agent 标记为 completed。
29. **inline fallback 显式化**：平台无法拉起子 agent 时，默认 blocked；只有用户明确批准，meta-po 才能用 `dispatch.mode=inline-fallback` 代执行，并记录 `fallback_reason`、`approved_by`、`approved_at`。结果必须写成 meta-po 代执行，不得写成 meta-dev / meta-qa 独立完成。

## CP0-CP8 检查点

| CP | 名称 | 类型 | 文件 |
|----|------|------|------|
| CP0 | 原始请求受理门 | 自动 | `process/checks/CP0-REQUEST-INTAKE.md` |
| CP1 | 用户场景完备门 | 自动 | `process/checks/CP1-USE-CASE-COMPLETENESS.md` |
| CP2 | 需求基线门 | 自动预检 + 人工 | `process/checks/CP2-REQUIREMENTS-BASELINE.md`；`checkpoints/CP2-REQUIREMENTS-BASELINE.md` |
| CP3 | HLD 架构评审门 | 自动预检 + 人工 | `process/checks/CP3-HLD-CONSISTENCY.md`；`checkpoints/CP3-HLD-REVIEW.md` |
| CP4 | Story 拆解与并行安全门 | 自动预检 + 人工 | `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md`；`checkpoints/CP4-STORY-PLAN-REVIEW.md` |
| CP5 | Story LLD 可实现性门 | 滚动自动预检 + 人工 | `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md`；`checkpoints/CP5-{story_id}-{story_slug}-LLD.md` |
| CP6 | Story 编码完成门 | 滚动自动 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md` |
| CP7 | Story 验证完成门 | 滚动自动 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md` |
| CP8 | 交付就绪门 | 自动预检 + 人工 | `process/checks/CP8-DELIVERY-READINESS.md`；`checkpoints/CP8-DELIVERY-READINESS.md` |

每个 CP 都必须包含 Entry Criteria、Checklist、Exit Criteria、Deliverables。自动检查点必须给出逐项检查结果；人工检查点必须给出 checklist 路径并回填人工审查结果。

CP6 / CP7 还必须包含 `Agent Dispatch Evidence` 小节。缺少 meta-dev / meta-qa 的真实子 agent 证据，且没有用户批准的 `inline-fallback` 时，结论只能是 `FAIL` 或 `BLOCKED`。

Claude Code 可继续使用结构化选择。Codex 也优先使用结构化选择 UI；无法提供时必须显式降级为 exact 文本确认：`1/approve/通过`、`2/修改: ...`、`3/reject/不通过`。

## 并行执行（Complex 模式）

Complex 模式下，LLD 写作、开发和验证均按 Story DAG 队列并行调度，但同一 Story 必须严格按：

`CP5 LLD 确认 → CP6 开发实现完成 → CP7 验证完成`

顺序推进。

默认并发上限：`max_parallel_lld=3`、`max_parallel_dev=2`、`max_parallel_qa=2`。开发并行必须同时满足依赖类型门控和文件所有权门控；`runtime` 依赖默认等待上游 `verified`，`file-conflict` 依赖默认串行。

## 方案评审规则（Design Review）

对 HLD / LLD / Story Plan / ADR 等设计产物评审时，必须逐条校验：

1. **内部一致性检查**：ADR、Risk、NFR、模块职责、流程图之间不得自相矛盾，发现矛盾必须在同一轮修订中解决。
2. **目标必须量化**：成功标准必须含可度量值（数量、百分比、字段集、覆盖率），禁止"不少于"、"尽可能"、"更完整"等无下限表述。
3. **集成契约显式化**：新 Agent / Skill / 模块必须定义与调用方和相邻对象的契约（调用方向、时机、触发方式、输入/输出、衔接、降级、调用方同步修改范围），禁止只声明"独立可调用"。
4. **相邻对象边界澄清**：非目标章节必须显式区分与相邻 Skill / Agent 的职责，避免"澄清 / 扩展 / 发现"等近义词默认重叠。
5. **前置校验与失败路径**：每个执行阶段必须定义前置校验和失败行为（终止 / 降级 / 回退），禁止"成功路径 only"。
6. **回退决策可操作化**：用户修改/回退必须映射为可枚举决策表（意图 → 目标 → 理由），禁止模糊"根据类型回退"。
7. **理论依据可追溯**：枚举型框架（维度、阶段、清单）必须说明来源方法论，或显式声明"可扩展"，避免被当作穷尽集合。
8. **遗留问题状态闭环**：待确认问题每次修订必须回写状态（OPEN / RESOLVED + 日期）；收敛后原行不删除以保留追溯。
9. **Gotchas 必有**：Skill 类产出（HLD / SKILL.md）必须含实质性 Gotchas 章节。
10. **修订记录完整**：每次迭代必须在产物头部追加修订记录（版本号 / 日期 / 修订人 / 变更要点精确到章节号）；该规则同样覆盖 `USE-CASES.md` 与 `REQUIREMENTS.md`。
11. **Story 拆解一致性**：§工作量章节的 Story 数、Wave 数必须与 §分阶段落地一一对应。
12. **决策与产物形态对齐**：ADR 结论必须回写到架构图、模块表、流程图、落地阶段；孤立 ADR 视为未落地。
13. **官方契约一致性**：平台路径、schema 或发现机制必须引用官方文档或 `delivery/doc/PLATFORM-CONTRACTS.yaml`；禁止按同平台目录类比推断。

## LLD 消费契约补充

- `STORY-*-LLD.md` 必须保留 14 个可见章节。
- `tier`、`shared_fragments`、`open_items` 为必读字段。
- meta-dev / meta-qa 必须把接口、异常、测试、回滚章节转成实施或验证输入，不能自行脑补缺失部分。

## Review Gate 分派与灰度

| Lane | Agent | 主要职责 |
|------|-------|----------|
| `lane-product` | `meta-pm` | 场景与范围一致性、原始需求 / 场景基线保留和修订记录 |
| `lane-architecture` | `meta-se` | 架构与依赖一致性 |
| `lane-implementation` | `meta-dev` | 可实现性与平台约束 |
| `lane-quality` | `meta-qa` | 可验证性与风险 |
| `lane-docs` | `meta-doc` | 交付文档可读性 |

灰度顺序：先 `HLD.md` / `STORY-*-LLD.md`，后 `ARCHITECTURE-DECISION.md` / `STORY-BACKLOG.md`，最后 `README.md` / `USER-MANUAL.md`。
