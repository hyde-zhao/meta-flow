# SCOPE-Pack 元工作流 — Copilot 全局指令

本会话运行 **SCOPE-Pack** 通用 Agent/Skill 工作流产物工厂。

---

## 角色与编排

- **主编排器**：`meta-po`（元工作流产品负责人），负责状态管理、阶段推进、人工检查点控制
- **功能 Agent**（按需启用）：`meta-pm`、`meta-se`、`meta-dev`、`meta-qa`、`meta-doc`
- **所有任务均通过 meta-po 发起**，功能 Agent 不直接响应用户，由 meta-po 唤醒和收敛

## Skill 发现路径

Skill 定义文件统一位于：`.agents/skills/<skill-name>/SKILL.md`

可用 Skills 及其触发词：

| Skill | 触发词 |
|-------|--------|
| `state-router` | 推进、下一步、当前状态、回退、状态查询、继续 |
| `requirement-extraction` | 提取需求、整理需求、结构化需求、需求分析 |
| `requirement-clarifier` | 澄清需求、需求问题、未决问题、需求歧义 |
| `scenario-expansion` | 展开场景、生成场景、测试场景、场景扩展 |
| `scope-normalization` | 归一化需求、去重、合并需求、范围整理 |
| `hld-designer` | HLD、高层设计、架构评审、架构方案、方案设计、架构设计、复杂度判定、设计方案、simple/standard/complex 判断 |
| `lld-designer` | LLD、详细设计、实现设计、Story 设计 |
| `claude-agent-writer` | 写 Claude Agent、创建 Claude 子代理、Claude subagent |
| `copilot-agent-writer` | 写 Copilot Agent、创建自定义 Agent、Copilot CLI Agent |
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
- **高层设计**：`process/HLD.md`
- **Skill 私有模板**：`skills/<skill-name>/templates/`
- **人工确认稿**：`checkpoints/`
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

1. **澄清锁**：`REQUIREMENTS.md` 未确认前，不得输出正式设计对象
2. **HLD 锁**：`HLD.md` 未经人工确认，不得进入 Story 拆解
3. **Story 锁**：未进入 `approved` 状态的 Story，不得开始 LLD 设计
4. **LLD 锁**：`STORY-{id}-LLD.md` 未确认前，不得开始该 Story 实现
5. **验证锁**：没有 `process/VALIDATION-ENV.yaml` 且 `approval.confirmed != true`，不得开始验证
6. **文档锁**：未完成验证和安装脚本生成，不得输出最终版 `README.md` 与 `USER-MANUAL.md`
7. **禁止越级改写**：`meta-dev` 不修改 REQUIREMENTS.md、HLD.md；`meta-qa` 不改设计对象；`meta-doc` 不改实现对象
8. **调研前置**：meta-pm 在场景发现前执行阶段零快速调研，记录至 CLARIFICATION-LOG.md
9. **确定性语言**：meta-se / meta-dev 产出使用确定性动词（创建/修改/删除）和量化条件，禁止模糊表述
10. **就绪检查**：meta-dev 开始实现前必须通过 Story 卡片完整性检查并确认 LLD 已获批
11. **测试策略前置**：meta-qa 验收前先输出 TEST-STRATEGY.md，指导验证过程
12. **输出隔离**：运行态写入 `process/`，确认稿写入 `checkpoints/`，交付物写入 `delivery/`；`.agents/` 和 `.github/` 仅存放元工作流自身定义
13. **Agent/Skill 关系维护**：开发或修改 Agent、Skill 时，若影响调用、适用或归属关系，必须同步更新 `skills/README.md`
14. **交付脚本边界**：`delivery/scripts/` 只允许安装器入口；Skill 运行时脚本必须放到 `delivery/skills/<skill>/scripts/`
15. **Skill 资产同树安装**：active Skill 引用的 `templates/`、`scripts/`、`schemas/`、`examples/` 资产必须与 Skill 同树存放，并使用 Skill 相对路径或 `<skill-root>/...`
16. **脚本安装验证**：active Skill 一旦新增脚本资产，必须验证 Claude Code / Codex 在 project 与 user scope 下安装后可直接执行
17. **缓存文件禁入库**：`__pycache__/`、`*.pyc` 及其他解释器缓存不是交付物，不得提交
18. **护栏静态检查**：提交前必须运行 `uv run --python 3.11 python scripts/check_delivery_guardrails.py`
19. **模式默认值**：若用户未显式声明“meta 工作流优化 / 自我开发”，工作流默认 `engagement_mode=production`
20. **场景主体默认值**：若用户未显式声明 meta 优化，`USE-CASES.md` 默认 `scenario_subject_type=target-artifact`，不得把当前仓库 / 当前工作流当成默认场景主体

## 人工检查点（5 类）

| 检查点 | 触发阶段 | 用户需确认的内容 |
|--------|---------|---------------|
| 需求确认 | requirement-clarification → solution-design | REQUIREMENTS.md 是否完整、无歧义 |
| HLD 确认 | solution-design → story-planning | HLD.md 是否完整、可接受 |
| Story 计划确认 | story-planning → story-execution | STORY-BACKLOG.md 边界与优先级 |
| Story LLD 确认 | story-execution 内逐个 Story | `STORY-{id}-LLD.md` 是否允许进入实现 |
| 终验 | documentation → delivered | 交付范围、安装脚本、版本信息是否完整 |

## 并行执行（Complex 模式）

Complex 模式下，同一 Wave 内的 Story 支持并行执行，但同一 Story 必须严格按：

`LLD 起草 → LLD 确认 → 开发实现 → 验证`

顺序推进。

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
10. **修订记录完整**：每次迭代必须在产物头部追加修订记录（版本号 / 日期 / 修订人 / 变更要点精确到章节号）。
11. **Story 拆解一致性**：§工作量章节的 Story 数、Wave 数必须与 §分阶段落地一一对应。
12. **决策与产物形态对齐**：ADR 结论必须回写到架构图、模块表、流程图、落地阶段；孤立 ADR 视为未落地。

## LLD 消费契约补充

- `STORY-*-LLD.md` 必须保留 14 个可见章节。
- `tier`、`shared_fragments`、`open_items` 为必读字段。
- meta-dev / meta-qa 必须把接口、异常、测试、回滚章节转成实施或验证输入，不能自行脑补缺失部分。

## Review Gate 分派与灰度

| Lane | Agent | 主要职责 |
|------|-------|----------|
| `lane-product` | `meta-pm` | 场景与范围一致性 |
| `lane-architecture` | `meta-se` | 架构与依赖一致性 |
| `lane-implementation` | `meta-dev` | 可实现性与平台约束 |
| `lane-quality` | `meta-qa` | 可验证性与风险 |
| `lane-docs` | `meta-doc` | 交付文档可读性 |

灰度顺序：先 `HLD.md` / `STORY-*-LLD.md`，后 `ARCHITECTURE-DECISION.md` / `STORY-BACKLOG.md`，最后 `README.md` / `USER-MANUAL.md`。
