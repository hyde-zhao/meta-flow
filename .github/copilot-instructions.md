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

- **运行时状态**：`.output/doc/STATE.md`
- **高层设计**：`.output/doc/HLD.md`
- **Skill 私有模板**：`skills/<skill-name>/templates/`
- **产物工作流模板**：`.output/templates/`
- **Story 卡片**：`.output/stories/STORY-*.md`
- **Story 级 LLD**：`.output/stories/STORY-*-LLD.md`
- **变更单**：`.output/changes/CR-*.md`

## 核心协议规则

1. **澄清锁**：`REQUIREMENTS.md` 未确认前，不得输出正式设计对象
2. **HLD 锁**：`HLD.md` 未经人工确认，不得进入 Story 拆解
3. **Story 锁**：未进入 `approved` 状态的 Story，不得开始 LLD 设计
4. **LLD 锁**：`STORY-{id}-LLD.md` 未确认前，不得开始该 Story 实现
5. **验证锁**：没有 `.output/doc/VALIDATION-ENV.yaml` 且 `approval.confirmed != true`，不得开始验证
6. **文档锁**：未完成验证和安装脚本生成，不得输出最终版 `README.md` 与 `USER-MANUAL.md`
7. **禁止越级改写**：`meta-dev` 不修改 REQUIREMENTS.md、HLD.md；`meta-qa` 不改设计对象；`meta-doc` 不改实现对象
8. **调研前置**：meta-pm 在场景发现前执行阶段零快速调研，记录至 CLARIFICATION-LOG.md
9. **确定性语言**：meta-se / meta-dev 产出使用确定性动词（创建/修改/删除）和量化条件，禁止模糊表述
10. **就绪检查**：meta-dev 开始实现前必须通过 Story 卡片完整性检查并确认 LLD 已获批
11. **测试策略前置**：meta-qa 验收前先输出 TEST-STRATEGY.md，指导验证过程
12. **输出隔离**：所有产物文件输出到 `.output/` 目录；`.agents/` 和 `.github/` 仅存放元工作流自身定义

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
