# SCOPE-Pack 元工作流 — Copilot 全局指令

本会话运行 **SCOPE-Pack** 通用 Agent/Skill 工作流产物工厂。

---

## 角色与编排

- **主编排器**：`meta-po`（元工作流产品负责人），负责状态管理、阶段推进、人工检查点控制
- **功能 Agent**（按需启用）：`meta-pm`、`meta-se`、`meta-dm`、`meta-dev`、`meta-qa`、`meta-doc`
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
| `solution-designer` | 方案设计、架构设计、复杂度判定、设计方案 |
| `claude-agent-writer` | 写 Claude Agent、创建 Claude 子代理、Claude subagent |
| `copilot-agent-writer` | 写 Copilot Agent、创建自定义 Agent、Copilot CLI Agent |
| `phase-designer` | 阶段划分、设计阶段、Phase 设计、执行顺序 |
| `wave-planner` | 并行分组、Wave 划分、并行计划、任务编排 |
| `dependency-mapper` | 依赖关系、DAG、任务依赖、前置依赖 |
| `story-manager` | 拆分 Story、Story 状态、Story 卡片、Story 管理 |
| `dag-validator` | DAG 校验、依赖校验、循环依赖检查 |
| `coverage-checker` | 覆盖率检查、场景覆盖、未覆盖场景 |
| `constraint-checker` | 约束检查、厂商兼容性、白名单检查、命令合规 |
| `dangerous-command-scan` | 危险命令、命令扫描、安全扫描、风险扫描 |
| `platform-validator` | 校验安装包、平台验证、结构校验 |
| `package-builder` | 打包、生成安装包、平台打包、构建安装包 |
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
| `vendor-profile-loader` | 加载厂商画像、厂商信息、设备能力、厂商约束 |
| `constraint-normalizer` | 归一化约束、标准化厂商约束、格式化约束、约束对齐 |
| `command-capability-map` | 命令映射、命令转换、厂商命令、设备命令 |

## 状态文件

- **运行时状态**：`.workflow-meta/STATE.md`（每轮对话结束后必须回写）
- **对象模板**：`.workflow-meta/templates/`
- **Story 卡片**：`.workflow-meta/stories/STORY-*.md`
- **变更单**：`.workflow-meta/changes/CR-*.md`

## 核心协议规则

1. **澄清锁**：`REQUIREMENTS.md` 未确认前，不得输出正式设计对象
2. **设计锁**：未经人工确认的设计，不得进入 Story 拆解
3. **Story 锁**：未进入 `approved` 状态的 Story，不得开始开发
4. **验证锁**：没有 `.workflow-meta/VALIDATION-ENV.yaml` 且 `approval.confirmed != true`，不得开始验证
5. **文档锁**：未完成验证和打包，不得输出最终版 `README.md` 与 `USER-MANUAL.md`
6. **禁止越级改写**：`meta-dev` 不修改 REQUIREMENTS.md；`meta-qa` 不改设计对象；`meta-doc` 不改实现对象
7. **上下文预算**：meta-po 持有上下文不超过总窗口 30%；功能 Agent 只加载本次任务必要对象文件

## 人工检查点（共 5 个）

| 检查点 | 触发阶段 | 用户需确认的内容 |
|--------|---------|---------------|
| 需求确认 | requirement-clarification → solution-design | REQUIREMENTS.md 是否完整、无歧义 |
| 设计确认 | solution-design → story-planning/skill-production | SOLUTION-DESIGN.md 方案模式是否认可 |
| Story 计划确认 | story-planning → story-development | STORY-BACKLOG.md 边界与优先级 |
| 验证环境确认 | story-development → verification | 提供 VALIDATION-ENV.yaml 或确认环境条件 |
| 终验 | documentation → delivered | 交付范围、平台包、版本信息是否完整 |

## 复杂度分流

用户提交需求后，meta-se 判定复杂度模式：

| 模式 | 触发条件 | 典型产物 |
|------|---------|---------|
| `simple` | 单一目标、单一角色、无复杂状态流转 | 1 个 SKILL.md + 安装包 |
| `standard` | 需要明确角色或少量步骤编排 | 1 个 Agent + 2~4 个 Skill |
| `complex` | 多角色协作、Story 拆解、并行开发 | 多 Agent 工作流包 |

## 并行执行（Complex 模式）

Complex 模式下，同一 Wave 内的 Story 支持通过 `/fleet` 命令并行执行：
- 每个后台子 Agent 消费独立 Story 卡片
- 所有子 Agent 通过文件系统交换状态（`STORY-STATUS.md`）
- Wave 结束后由 meta-po 统一收敛，进入下一 Wave 或验证阶段
