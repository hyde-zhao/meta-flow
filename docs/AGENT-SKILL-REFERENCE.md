# SCOPE-Pack Agent/Skill 使用参考手册

本文档是 SCOPE-Pack 元工作流系统中所有 Agent 和 Skill 的详细使用参考。

> 📖 安装方法见 [`USER_GUIDE.md`](./USER_GUIDE.md)

---

## 目录

- [一、Agent 使用参考](#一agent-使用参考)
- [二、Skill 使用参考](#二skill-使用参考)
- [三、典型对话示例](#三典型对话示例)
- [四、状态机与检查点](#四状态机与检查点)

---

## 一、Agent 使用参考

系统共有 **7 个 Agent**，由 `meta-po` 统一编排。用户通常只需与 `meta-po` 交互，其他 Agent 在流程推进时自动被唤醒。

### 唤醒规则

- **Copilot CLI**：在对话中直接 `@meta-po`，或说"开始新工作流"
- **Claude Code**：Agents 在项目目录下自动加载，无需显式唤醒
- **Codex**：在对话头部描述任务，对应 Agent 根据 description 自动匹配

---

### `meta-po` — 元流编排器（主入口）

| 属性 | 说明 |
|------|------|
| **职责** | 读写 `STATE.md`、推进阶段、触发检查点、受理变更请求 |
| **何时激活** | 对话开始时 / 每轮开头读取状态 |
| **不做什么** | 不直接写需求、方案、代码或文档 |

**如何启动工作流：**

```text
我需要生成一个新的 Agent/Skill 工作流。
目标：[用一句话描述你的目标]
目标平台：[copilot / claude-code / codex / openclaw]
```

**如何查询当前进度：**

```text
当前状态是什么？
```

**如何发起变更请求：**

```text
需求变更：[描述变更内容和原因]
```

**检查点响应：** meta-po 会在 5 个关键节点暂停并请求人工确认：
1. `[检查点1] 需求确认` — REQUIREMENTS.md 生成后
2. `[检查点2] 设计确认` — SOLUTION-DESIGN.md 和架构决策后
3. `[检查点3] Story 计划确认` — STORY-BACKLOG.md 生成后
4. `[检查点4] 验证环境确认` — 进入验证前
5. `[检查点5] 终验` — 所有 Story 验证通过、包构建后

---

### `meta-pm` — 需求澄清专家

| 属性 | 说明 |
|------|------|
| **职责** | 多轮提问澄清需求、生成 `REQUIREMENTS.md`、维护 `CLARIFICATION-LOG.md` |
| **触发条件** | `meta-po` 在 `requirement-clarification` 阶段唤醒 |
| **输出产物** | `REQUIREMENTS.md`（结构化需求清单） |

**直接触发示例（Copilot CLI）：**

```text
澄清需求：[描述模糊的需求]
```

**说明：** meta-pm 会逐轮提问，不会一次性抛出所有问题。每轮最多 3 个问题。当需求充分清晰后输出 REQUIREMENTS.md，并请求 meta-po 推进到下一阶段。

---

### `meta-se` — 架构设计师

| 属性 | 说明 |
|------|------|
| **职责** | 判断 simple/standard/complex 模式、输出 `SOLUTION-DESIGN.md`、`ARCHITECTURE-DECISION.md` |
| **触发条件** | `meta-po` 在 `solution-design` 阶段唤醒 |
| **判断规则** | 单能力模块→simple；单角色+多能力→standard；多角色协作→complex |
| **输出产物** | `SOLUTION-DESIGN.md`、`ARCHITECTURE-DECISION.md` |

**直接触发示例：**

```text
方案设计：基于已确认的需求，输出设计方案
```

---

### `meta-dm` — 开发经理

| 属性 | 说明 |
|------|------|
| **职责** | Story 拆解、Wave 并行规划、生成 `STORY-BACKLOG.md`、`DEVELOPMENT-PLAN.yaml` |
| **触发条件** | `meta-po` 在 `story-planning` 阶段唤醒（standard/complex 模式） |
| **并行规则** | 无依赖且无文件冲突的 Story 可分入同一 Wave 并行 |
| **输出产物** | `STORY-BACKLOG.md`、`DEVELOPMENT-PLAN.yaml` |

**直接触发示例：**

```text
拆分 Story：根据设计方案拆解开发任务
```

---

### `meta-dev` — 实现工程师

| 属性 | 说明 |
|------|------|
| **职责** | 逐 Story 实现 Agent/Skill/模板产物，自检 8 维度验收标准 |
| **触发条件** | `meta-po` 在 `skill-production` 阶段逐 Story 唤醒 |
| **命名规范** | 所有输出文件名必须为 kebab-case（如 `requirement-clarifier.md`） |
| **3-piece 规范** | 每个 Story 卡片必须包含 `dev_context` + `validation_context` + `acceptance_criteria` |
| **输出产物** | `SKILL.md` / `agent.md` / 模板文件 |

**直接触发示例：**

```text
请实现 Story [Story-ID]：[Story 标题]
```

---

### `meta-qa` — 质量工程师

| 属性 | 说明 |
|------|------|
| **职责** | 8 维度验收、安全扫描、平台打包、生成 `VERIFICATION-REPORT.md` |
| **触发条件** | 所有 Story 实现完成后由 `meta-po` 唤醒 |
| **验收维度** | 功能完整性、Frontmatter 合规、命名规范、平台兼容性、安全扫描、文件引用、触发词有效性、安装可用性 |
| **输出产物** | `VERIFICATION-REPORT.md`、各平台安装包、`INSTALL-CHECKSUMS.sha256` |

**直接触发示例：**

```text
生成安装包：[目标平台]
```

```text
校验安装包：验证目录结构是否符合平台规范
```

---

### `meta-doc` — 文档工程师

| 属性 | 说明 |
|------|------|
| **职责** | 生成 `README.md`（安装说明）和 `USER-MANUAL.md`（使用手册） |
| **触发条件** | `meta-qa` 验收通过后由 `meta-po` 唤醒 |
| **输出产物** | `README.md`、`USER-MANUAL.md` |

**直接触发示例：**

```text
输出文档：根据已完成的工作流生成 README 和用户手册
```

---

## 二、Skill 使用参考

Skills 通过**触发词**自动激活，无需显式指定名称。Copilot CLI 在 `.github/copilot/copilot-instructions.md` 中声明了所有触发词映射。

系统共有 **25 个通用 Skill**，按功能分为 5 组。

---

### 组 1：需求分析类

#### `requirement-extraction` — 需求提取

| 项目 | 内容 |
|------|------|
| **触发词** | 提取需求、整理需求、结构化需求、需求分析 |
| **输入提示** | 自然语言需求描述 或 `input_spec.yaml` 路径 |
| **输出** | 结构化 `REQUIREMENTS.md` |

```text
# 示例调用
提取需求：用户希望有一个可以自动识别并拒绝恶意 Prompt 的安全 Skill
```

---

#### `requirement-clarifier` — 需求澄清

| 项目 | 内容 |
|------|------|
| **触发词** | 澄清需求、需求问题、未决问题、需求歧义、需求不清晰 |
| **输入提示** | 可选：需求条目 ID 或关键词 |
| **输出** | 分轮提问清单 + 更新后的 `CLARIFICATION-LOG.md` |

```text
# 示例调用
澄清需求 REQ-003：输出范围不清晰，是单平台还是多平台？
```

---

#### `scope-normalization` — 需求归一化

| 项目 | 内容 |
|------|------|
| **触发词** | 归一化需求、去重、合并需求、范围整理、消除歧义 |
| **输入提示** | `REQUIREMENTS.md` 路径 |
| **输出** | 去重合并后的更新版 `REQUIREMENTS.md` |

```text
# 示例调用
归一化需求：合并 REQ-002 和 REQ-005，它们描述的是同一个功能
```

---

#### `scenario-expansion` — 场景展开

| 项目 | 内容 |
|------|------|
| **触发词** | 展开场景、生成场景、测试场景、场景扩展 |
| **输入提示** | `REQUIREMENTS.md` 路径 |
| **输出** | `SCENARIOS.yaml`（每条需求对应的测试场景） |

```text
# 示例调用
展开场景：为 REQUIREMENTS.md 中所有需求生成测试场景
```

---

### 组 2：方案设计类

#### `solution-designer` — 方案设计

| 项目 | 内容 |
|------|------|
| **触发词** | 方案设计、架构设计、复杂度判定、设计方案、simple/standard/complex |
| **输入提示** | 可选：目标平台约束 |
| **输出** | `SOLUTION-DESIGN.md`（含复杂度判定 + 3 个关键设计决策） |

```text
# 示例调用
方案设计：基于当前 REQUIREMENTS.md，判断复杂度并输出架构方案，目标平台为 claude-code
```

---

#### `phase-designer` — 阶段划分

| 项目 | 内容 |
|------|------|
| **触发词** | 阶段划分、设计阶段、Phase 设计、执行顺序 |
| **输入提示** | `REQUIREMENTS.md` 和 `SCENARIOS.yaml` 路径 |
| **输出** | `WORKFLOW-PLAN.yaml`（Phase 结构） |

```text
# 示例调用
阶段划分：根据需求场景设计执行阶段顺序
```

---

#### `dependency-mapper` — 依赖关系建立

| 项目 | 内容 |
|------|------|
| **触发词** | 依赖关系、DAG、任务依赖、前置依赖 |
| **输入提示** | `WORKFLOW-PLAN.yaml`（已有 tasks） |
| **输出** | 更新后的 `WORKFLOW-PLAN.yaml`（含 `depends_on` 字段） |

```text
# 示例调用
建立依赖关系：分析 WORKFLOW-PLAN 中各任务的前置依赖
```

---

#### `wave-planner` — 并行分组

| 项目 | 内容 |
|------|------|
| **触发词** | 并行分组、Wave 划分、并行计划、任务编排 |
| **输入提示** | `WORKFLOW-PLAN.yaml`（已有 phases） |
| **输出** | 分组后的 Wave 结构（哪些任务可并行） |

```text
# 示例调用
Wave 划分：根据依赖关系将任务分为可并行的 Wave 组
```

---

### 组 3：Story 管理类

#### `story-manager` — Story 生命周期管理

| 项目 | 内容 |
|------|------|
| **触发词** | 拆分 Story、Story 状态、Story 卡片、Story 创建、Story 更新 |
| **输入提示** | 可选：Story ID 或操作类型（create/update/status） |
| **输出** | Story 卡片（3-piece 格式）/ 状态更新 / `STORY-STATUS.md` |

```text
# 创建 Story
拆分 Story：将 REQ-001 拆解为可开发的 Story 卡片

# 更新状态
Story 状态 STORY-003：更新为 in-verification

# 查询所有 Story 进度
Story 状态：输出当前所有 Story 的进度汇总
```

**Story 状态流转：**

```
draft → approved → in-development → in-verification → done
                                                     ↘ blocked
```

---

#### `state-router` — 状态推进

| 项目 | 内容 |
|------|------|
| **触发词** | 推进、下一步、当前状态、回退、状态查询、继续 |
| **输入提示** | 可选：目标状态或查询字段 |
| **输出** | 状态转换建议 / 下一步应调用的 Agent |

```text
# 查询当前状态
当前状态是什么？

# 推进到下一阶段
继续：需求已确认，推进到设计阶段

# 回退
回退：设计方案需要修改，回到需求澄清
```

---

#### `context-handoff` — 上下文交接

| 项目 | 内容 |
|------|------|
| **触发词** | 上下文交接、装配上下文、阶段切换、交接给 |
| **输入提示** | 目标 Agent 名称 |
| **输出** | 精简后的上下文摘要（不超过总 token 的 30%） |

```text
# 示例调用
上下文交接给 meta-dev：准备开始 STORY-001 的开发
```

---

### 组 4：质量与安全类

#### `dangerous-command-scan` — 安全扫描

| 项目 | 内容 |
|------|------|
| **触发词** | 危险命令、命令扫描、安全扫描、风险扫描、Prompt 注入检测 |
| **输入提示** | 可选：目标文件或目录路径（默认扫描当前产物） |
| **输出** | 风险报告（BLOCKING / WARNING 分级） |
| **扫描范围** | 系统命令、文件系统操作、Prompt 注入（指令覆盖/角色劫持/越狱/提示词泄露） |

```text
# 扫描指定文件
安全扫描：.agents/agents/meta-po.md

# 扫描全部产物
安全扫描：扫描 .agents/ 目录下所有 Agent 和 Skill
```

---

#### `permission-boundary-check` — 权限边界检查

| 项目 | 内容 |
|------|------|
| **触发词** | 权限检查、权限边界、越权验证、安全边界 |
| **输入提示** | `input_spec.yaml` 和 `WORKFLOW-PLAN.yaml` 路径 |
| **输出** | 权限越界报告 |

```text
# 示例调用
权限检查：验证工作流中的操作是否在声明的权限范围内
```

---

#### `runtime-risk-review` — 运行时风险复核

| 项目 | 内容 |
|------|------|
| **触发词** | 运行时风险、DryRun、执行环境、隔离检查 |
| **输入提示** | `WORKFLOW-PLAN.yaml` 路径 |
| **输出** | 运行时风险清单（DryRun 支持、隔离措施、权限最小化） |

```text
# 示例调用
运行时风险：检查当前工作流是否支持 DryRun 模式
```

---

#### `dag-validator` — DAG 校验

| 项目 | 内容 |
|------|------|
| **触发词** | DAG 校验、依赖校验、循环依赖检查 |
| **输入提示** | `WORKFLOW-PLAN.yaml` 路径 |
| **输出** | 校验报告（是否存在环路、无效引用） |

```text
# 示例调用
DAG 校验：检查 WORKFLOW-PLAN.yaml 中是否存在循环依赖
```

---

#### `coverage-checker` — 场景覆盖检查

| 项目 | 内容 |
|------|------|
| **触发词** | 覆盖率检查、场景覆盖、未覆盖场景 |
| **输入提示** | `SCENARIOS.yaml` 和 `WORKFLOW-PLAN.yaml` 路径 |
| **输出** | 覆盖率报告（哪些场景未被计划覆盖） |

```text
# 示例调用
覆盖率检查：验证所有测试场景是否都有对应的工作流任务
```

---

### 组 5：交付与反馈类

#### `package-builder` — 平台打包

| 项目 | 内容 |
|------|------|
| **触发词** | 打包、生成安装包、平台打包、构建安装包、生成平台包 |
| **输入提示** | 可选：目标平台（copilot/claude-code/codex/openclaw） |
| **输出** | `packages/` 下对应平台目录 + `INSTALL-CHECKSUMS.sha256` |

```text
# 构建全部平台
打包：构建全平台安装包

# 构建单平台
生成安装包：只构建 copilot 平台包
```

---

#### `platform-validator` — 安装包结构校验

| 项目 | 内容 |
|------|------|
| **触发词** | 校验安装包、平台验证、结构校验、安装结构检查、目录规范校验 |
| **输入提示** | 可选：目标平台或包路径 |
| **输出** | 各平台结构校验报告（5 个维度） |

```text
# 示例调用
校验安装包：验证 claude-code 平台包的目录结构是否合规
```

---

#### `workflow-renderer` — 工作流文档渲染

| 项目 | 内容 |
|------|------|
| **触发词** | 渲染工作流、生成文档、交付文档、输出工作流 |
| **输入提示** | `WORKFLOW-PLAN.yaml` 路径 |
| **输出** | 人类可读的交付文档（Markdown 格式） |

```text
# 示例调用
渲染工作流：将 WORKFLOW-PLAN.yaml 输出为可读文档
```

---

#### `context-manifest-builder` — 执行上下文清单

| 项目 | 内容 |
|------|------|
| **触发词** | 上下文清单、执行上下文、CONTEXT-MANIFEST |
| **输入提示** | `WORKFLOW-PLAN.yaml` 路径 |
| **输出** | `CONTEXT-MANIFEST.yaml` |

```text
# 示例调用
执行上下文：为当前工作流生成 CONTEXT-MANIFEST
```

---

#### `issue-drafter` — 问题工单起草

| 项目 | 内容 |
|------|------|
| **触发词** | 起草问题、创建 ISSUE、问题工单、报告问题 |
| **输入提示** | RUN-EXEC 记录路径 或 问题描述 |
| **输出** | `ISSUE-*.md` 工单文件 |

```text
# 示例调用
创建 ISSUE：Story-002 验证失败，Skill 触发词未被识别
```

---

#### `issue-routing` — 问题工单路由

| 项目 | 内容 |
|------|------|
| **触发词** | 路由问题、分配问题、ISSUE 路由、问题分流 |
| **输入提示** | ISSUE 工单 ID 或问题描述 |
| **输出** | 分类定级报告 + 建议路由到的 Agent |

```text
# 示例调用
ISSUE 路由：ISSUE-001 应该由哪个 Agent 处理？
```

---

#### `run-feedback-parser` — 执行反馈记录

| 项目 | 内容 |
|------|------|
| **触发词** | 执行反馈、提交反馈、记录执行结果、执行记录 |
| **输入提示** | 执行反馈的自然语言描述 或结构化数据 |
| **输出** | 标准 `RUN-EXEC-*.md` 记录 |

```text
# 示例调用
执行反馈：Story-003 在 claude-code 上安装成功，skill 触发正常，无异常
```

---

#### `regression-subset-builder` — 最小回归集

| 项目 | 内容 |
|------|------|
| **触发词** | 回归测试、最小回归集、修复验证、回归范围 |
| **输入提示** | ISSUE ID 或修复涉及的 artifact 列表 |
| **输出** | `REGRESSION-TEST-SUBSET.yaml` |

```text
# 示例调用
回归测试：ISSUE-001 已修复，生成最小验证范围
```

---

#### `change-impact-analysis` — 变更影响分析

| 项目 | 内容 |
|------|------|
| **触发词** | 需求变更、修改需求、变更影响、发起变更、CR |
| **输入提示** | 变更原因、变更类型（add/modify/delete）、影响范围描述 |
| **输出** | `CR-*.md`（5 维度影响分析：需求/设计/Story/验证/文档） |

```text
# 示例调用
需求变更：新增对 OpenClaw 平台的支持，需要评估影响范围
```

---

## 三、典型对话示例

### 示例 A：Simple 模式 — 生成单个 Skill

```text
用户：我需要一个能自动摘要需求澄清历史的 Skill，部署到 Copilot CLI。

meta-po：收到。启动需求澄清阶段，唤醒 meta-pm。

meta-pm：请问这个 Skill 的触发场景是什么？是每轮对话结束自动触发，
          还是用户主动调用？

用户：用户主动调用，说"生成澄清摘要"时触发。

meta-pm：理解。输入是对话历史，还是 CLARIFICATION-LOG.md 文件？

用户：读取 CLARIFICATION-LOG.md 文件。

meta-pm：需求已充分。输出 REQUIREMENTS.md，请确认。
          [REQUIREMENTS.md 内容]

用户：确认。

meta-po：[检查点1 通过] 唤醒 meta-se 进行方案设计。

meta-se：复杂度判定：simple（单一能力模块）。
          无需 Agent，直接输出 SKILL.md。唤醒 meta-dev。

meta-dev：输出 clarification-summarizer/SKILL.md
          [文件内容]

meta-qa：安全扫描通过，Frontmatter 合规，命名规范。
          生成 Copilot 平台包：packages/copilot/...
          
meta-doc：输出 README.md 和 USER-MANUAL.md。

meta-po：[检查点5 终验] 所有产物已就绪，请确认交付。
```

---

### 示例 B：Standard 模式 — 生成 Agent + Skill

```text
用户：我需要一个 Story 管理 Agent，配合 3 个 Skill：创建 Story、
      更新状态、生成周报。部署到 Claude Code。

meta-pm：[澄清] Story 卡片格式是否有固定模板要求？

用户：需要包含验收标准和开发上下文，用 YAML 头部。

meta-pm：[澄清] 周报输出格式是 Markdown 还是 YAML？

用户：Markdown，便于 PR 描述引用。

meta-pm：需求确认完成。

meta-se：复杂度判定：standard（1 Agent + 3 Skill）。
          架构决策：story-manager.md 作为主 Agent，
          create-story / update-story-status / generate-story-report 为 3 个 Skill。
          
meta-po：[检查点2] 设计方案待确认，是否批准？

用户：批准。

meta-dm：无需 Wave 并行（仅 4 个产物，无依赖冲突）。生成 STORY-BACKLOG.md。

meta-po：[检查点3] Story 计划待确认。

用户：确认。

meta-dev：[实现 STORY-001] story-manager.md ✓
meta-dev：[实现 STORY-002] create-story/SKILL.md ✓
meta-dev：[实现 STORY-003] update-story-status/SKILL.md ✓
meta-dev：[实现 STORY-004] generate-story-report/SKILL.md ✓

meta-po：[检查点4] 请提供验证环境配置。

用户：验证环境：本地 claude-code，项目目录 /home/user/myproject

meta-qa：8 维度验收通过。生成 claude-code 安装包。

meta-doc：README.md + USER-MANUAL.md 已输出。

meta-po：[检查点5] 交付完成，请终验。
```

---

### 示例 C：直接调用单个 Skill

```text
# 不启动完整工作流，直接使用某个 Skill
用户：安全扫描：检查 .agents/agents/meta-po.md 是否有 Prompt 注入风险

# dangerous-command-scan 触发
系统：扫描 meta-po.md...
      [Prompt 注入检测] 第一层（指令覆盖）：无风险
      [Prompt 注入检测] 第二层（角色劫持）：无风险
      [Prompt 注入检测] 第三层（越狱尝试）：无风险
      [Prompt 注入检测] 第四层（提示词泄露）：无风险
      [系统命令扫描]：无危险命令
      结论：PASS，0 个风险项
```

---

## 四、状态机与检查点

### 工作流状态（存储在 `.workflow-meta/STATE.md`）

| 状态 | 说明 | 主要 Agent |
|------|------|-----------|
| `init` | 初始化，等待用户目标 | meta-po |
| `requirement-clarification` | 需求澄清进行中 | meta-pm |
| `requirement-confirmed` | 需求已人工确认 | meta-po |
| `solution-design` | 方案设计进行中 | meta-se |
| `design-confirmed` | 方案已人工确认 | meta-po |
| `story-planning` | Story 拆解与规划 | meta-dm |
| `story-confirmed` | Story 计划已确认 | meta-po |
| `skill-production` | Story 开发进行中 | meta-dev |
| `verification` | 验收与安全扫描 | meta-qa |
| `packaging` | 平台包构建 | meta-qa |
| `documentation` | 文档生成 | meta-doc |
| `delivered` | 交付完成 | meta-po |

### 检查点（人工必须确认）

| 检查点 | 触发时机 | 用户操作 |
|--------|---------|---------|
| `[检查点1] 需求确认` | REQUIREMENTS.md 生成后 | 审阅并回复"确认"或"修改：..." |
| `[检查点2] 设计确认` | SOLUTION-DESIGN.md 生成后 | 审阅架构决策并确认 |
| `[检查点3] Story 计划确认` | STORY-BACKLOG.md 生成后 | 确认 Story 拆解范围 |
| `[检查点4] 验证环境确认` | 进入 verification 前 | 提供或确认 VALIDATION-ENV.yaml |
| `[检查点5] 终验` | 所有产物就绪后 | 最终审阅并批准交付 |

### 变更请求流程

在任意阶段均可发起变更：

```text
需求变更：[描述变更]
```

meta-po 会调用 `change-impact-analysis` Skill，生成 `CR-*.md`，进行 5 维度影响分析（需求/设计/Story/验证/文档），并请求人工确认是否接受变更。

---

## 五、工作流文件系统详解

工作流运行期间会在项目目录下产生一系列文件，这些文件既是 Agent 之间的通信媒介，也是整个工作流的持久化状态存储。

### 5.1 总体目录结构

```
your-project/
│
├── .workflow-meta/              # 工作流运行时根目录
│   ├── STATE.md                 # 状态机（核心，每轮必读必写）
│   ├── REQUEST.md               # 用户目标原文
│   ├── REQUIREMENTS.md          # 结构化需求清单
│   ├── CLARIFICATION-LOG.md     # 多轮澄清历史
│   ├── SOLUTION-DESIGN.md       # 方案设计
│   ├── ARCHITECTURE-DECISION.md # 架构决策（Agent/Skill 组合）
│   ├── STORY-BACKLOG.md         # Story 列表
│   ├── STORY-STATUS.md          # Story 实时进度汇总
│   ├── DEVELOPMENT-PLAN.yaml    # Wave/Lane 并行计划
│   ├── VALIDATION-ENV.yaml      # 验证环境配置（人工提供）
│   ├── VERIFICATION-REPORT.md   # 8 维度验收报告
│   ├── PACKAGE-MANIFEST.yaml    # 打包产物清单（含 SHA256）
│   │
│   ├── stories/                 # Story 卡片（每个 Story 一个文件）
│   │   ├── STORY-001.md
│   │   ├── STORY-002.md
│   │   └── ...
│   │
│   ├── changes/                 # 变更请求工单
│   │   ├── CR-001.md
│   │   └── ...
│   │
│   ├── packages/                # 工作流内部构建中间产物
│   └── templates/               # 所有文件的初始模板
│
├── .agents/                     # Agent/Skill 源文件（不随项目变化）
│   ├── agents/                  # 7 个 SCOPE-Pack Agent
│   └── skills/                  # 25 个通用 Skill
│
└── packages/                    # 最终交付的平台安装包
    ├── copilot/
    ├── claude-code/
    ├── codex/
    ├── openclaw/
    └── INSTALL-CHECKSUMS.sha256
```

---

### 5.2 核心状态文件：`STATE.md`

**路径**：`.workflow-meta/STATE.md`  
**创建者**：`meta-po`（工作流初始化时）  
**读写规则**：每轮对话 meta-po **必须先读取**，结束前**必须回写**

```yaml
---
project_id: "scope-pack-demo-01"     # 项目唯一 ID
workflow_mode: "standard"             # simple / standard / complex
current_phase: "story-planning"       # 当前阶段（见状态机）
current_agent: "meta-dm"             # 当前负责 Agent
iteration: 5                          # 总轮次计数
blocked: false                        # 是否阻塞
last_action: "meta-se 完成方案设计"   # 上一步做了什么
next_action: "唤醒 meta-dm 拆分 Story" # 下一步计划
checkpoints:
  requirement_confirmed: true         # 需求已确认
  design_confirmed: true              # 设计已确认
  story_plan_confirmed: false         # Story 计划待确认
  validation_env_ready: false
  final_package_verified: false
  documentation_done: false
parallel_waves: []                    # 当前并行中的 Wave 列表
history:                              # 阶段历史（追加，不覆盖）
  - phase: init
    action: "初始化 REQUEST.md"
    timestamp: "2026-04-04T09:00:00Z"
last_updated: "2026-04-04T09:30:00Z"
---
```

**状态转换表**：

| 当前阶段 | 退出条件 | 下一阶段 |
|---------|---------|---------|
| `init` | REQUEST.md 已填写 | `requirement-clarification` |
| `requirement-clarification` | REQUIREMENTS.md `confirmed=true` 且无 BLOCKING 未决项 | `solution-design` |
| `solution-design` | ARCHITECTURE-DECISION.md `confirmed=true` | `skill-production`（simple）/ `story-planning`（standard/complex）|
| `story-planning` | STORY-BACKLOG.md + DEVELOPMENT-PLAN.yaml 人工确认 | `story-development` |
| `story-development` | 当前 Wave 所有 Story = `ready-for-verification` | `verification` |
| `skill-production` | Skill 文件输出完成 | `verification` |
| `verification` | VERIFICATION-REPORT.md 无 BLOCKING 未通过项 | `packaging` |
| `packaging` | PACKAGE-MANIFEST.yaml + 平台包生成 | `documentation` |
| `documentation` | README.md + USER-MANUAL.md 生成 | `human-final-review` |
| `human-final-review` | 人工批准 | `delivered` |

---

### 5.3 需求阶段文件

#### `REQUEST.md`

**路径**：`.workflow-meta/REQUEST.md`  
**创建者**：`meta-po`（首轮对话后立即创建）  
**内容**：用户原始目标原文 + 目标平台

```markdown
---
request_id: "REQ-20260404-001"
submitted_at: "2026-04-04T09:00:00Z"
submitted_by: "user"
---

## 用户目标
[保留原文，不做修改]

## 目标平台
copilot, claude-code
```

---

#### `REQUIREMENTS.md`

**路径**：`.workflow-meta/REQUIREMENTS.md`  
**创建者**：`meta-pm`  
**状态字段**：`status: draft → confirmed`（人工在检查点1确认后变更）

```markdown
---
status: confirmed
version: "1.2"
confirmed_by: "user"
confirmed_at: "2026-04-04T09:15:00Z"
---

## 需求条目

| ID   | 需求描述                           | 优先级 | 验收条件              | 来源       |
|------|-----------------------------------|--------|----------------------|------------|
| R001 | Skill 需支持触发词自动识别         | P0     | 触发词命中率 100%     | 用户原始输入 |
| R002 | 输出产物须通过 Frontmatter 校验    | P1     | 无缺失必填字段        | 澄清第1轮  |
```

---

#### `CLARIFICATION-LOG.md`

**路径**：`.workflow-meta/CLARIFICATION-LOG.md`  
**创建者**：`meta-pm`  
**写入规则**：每轮追加，**不覆盖历史**

```markdown
---
status: in-progress
current_round: 2
total_rounds: 2
ready_for_design: true
---

### 第 1 轮澄清（2026-04-04）

**问题 1**：触发词需要支持中英文混合吗？  
**回答**：是的，中英文均需支持。

**问题 2**：Skill 输出需要包含示例用法吗？  
**回答**：需要，放在 SKILL.md 的 examples 部分。
```

---

### 5.4 设计阶段文件

#### `SOLUTION-DESIGN.md`

**路径**：`.workflow-meta/SOLUTION-DESIGN.md`  
**创建者**：`meta-se`  
**关键字段**：`complexity`（决定后续流程分支）

```markdown
---
complexity: "standard"
confirmed: true
confirmed_by: "user"
confirmed_at: "2026-04-04T09:20:00Z"
---

## 复杂度判定
**模式**：standard

**判定理由**：需求包含 1 个主角色 + 3 个能力模块，无多 Agent 协作需求。

## 三个关键设计决策
1. 主 Agent 文件命名：`story-manager.md`
2. 3 个 Skill 独立目录，遵循 kebab-case 命名
3. 目标平台：claude-code + copilot
```

---

#### `ARCHITECTURE-DECISION.md`

**路径**：`.workflow-meta/ARCHITECTURE-DECISION.md`  
**创建者**：`meta-se`  
**人工确认**：检查点2，`confirmed` 字段由 meta-po 在用户回复后置 `true`

```markdown
---
complexity: "standard"
confirmed: true
confirmed_by: "user"
confirmed_at: "2026-04-04T09:22:00Z"
---

## Agent/Skill 组合方案

| 角色 | 文件名 | 职责 | 关联 Skill |
|------|--------|------|-----------|
| 主 Agent | story-manager.md | Story 生命周期管理 | 以下 3 个 |

## Skill 清单

| Skill 名称 | 文件路径 | 触发词 |
|-----------|---------|--------|
| create-story | create-story/SKILL.md | 创建 Story、新建 Story |
| update-story-status | update-story-status/SKILL.md | 更新状态、Story 状态 |
| generate-story-report | generate-story-report/SKILL.md | 生成周报、Story 周报 |
```

---

### 5.5 Story 阶段文件

#### `STORY-BACKLOG.md`

**路径**：`.workflow-meta/STORY-BACKLOG.md`  
**创建者**：`meta-dm`  
**读取者**：`meta-po`（推进时）、`meta-dev`（开发时）

```markdown
---
version: "1.0"
last_updated: "2026-04-04T09:25:00Z"
---

## Story 列表

| Story ID  | 标题               | 优先级 | Wave | 状态   | 依赖  |
|-----------|--------------------|--------|------|--------|-------|
| STORY-001 | 实现 story-manager | P0     | W1   | draft  | —     |
| STORY-002 | 实现 create-story  | P0     | W2   | draft  | S-001 |

## Wave 分组

**Wave 1**（串行基础）：STORY-001  
**Wave 2**（并行）：STORY-002, STORY-003, STORY-004
```

---

#### `stories/STORY-NNN.md`（3-piece Story 卡片）

**路径**：`.workflow-meta/stories/STORY-001.md`  
**创建者**：`meta-dm`（卡片结构）+ `meta-dev`（实现内容填充）  
**3-piece 强制要求**：必须同时包含 `dev_context`、`validation_context`、`acceptance_criteria`

```markdown
---
story_id: "STORY-001"
title: "实现 story-manager Agent"
status: "in-development"
priority: "P0"
wave: "W1"
depends_on: []
created_at: "2026-04-04T09:25:00Z"
updated_at: "2026-04-04T10:00:00Z"
---

## 目标
实现 story-manager.md，使其能管理 Story 的完整生命周期。

## 开发上下文（dev_context）
- **输入文件**：REQUIREMENTS.md, ARCHITECTURE-DECISION.md
- **输出文件**：.agents/agents/story-manager.md
- **设计约束**：使用 H1+blockquote 格式，无需 Frontmatter
- **命名规范**：kebab-case
- **平台目标**：claude-code, copilot

## 验证上下文（validation_context）
- **验证入口**：platform-validator
- **验证方式**：dangerous-command-scan + Frontmatter 检查
- **依赖环境**：参见 VALIDATION-ENV.yaml

## 量化验收标准（acceptance_criteria）
- [ ] 完整性：输出 1 个 .md 文件
- [ ] 平台适配：符合 claude-code PLATFORM-INSTALL-SPEC.md
- [ ] 安全合规：dangerous-command-scan 0 风险项
- [ ] 命名规范：文件名符合 ^[a-z][a-z0-9-]+\.md$
- [ ] Frontmatter：H1 格式（Agent 无需 Frontmatter）
- [ ] 可安装性：DryRun 结构校验通过
```

**Story 状态流转**：

```
draft → approved → in-development → in-verification → done
                                                     ↘ blocked（附阻塞原因）
```

---

#### `STORY-STATUS.md`

**路径**：`.workflow-meta/STORY-STATUS.md`  
**创建者**：`meta-dm`（初始化），`meta-dev`/`meta-qa`（实时回写）  
**用途**：并行 Wave 中各 sub-agent 写入自己的 Story 结果，meta-po 轮询判断 Wave 是否完成

```markdown
---
last_updated: "2026-04-04T10:30:00Z"
---

## Wave 1 进度

| Story ID  | 状态         | 产物                  | 阻塞 |
|-----------|-------------|----------------------|------|
| STORY-001 | done        | story-manager.md     | 否   |

## Wave 2 进度

| Story ID  | 状态            | 产物 | 阻塞 |
|-----------|----------------|------|------|
| STORY-002 | in-development | —    | 否   |
| STORY-003 | in-development | —    | 否   |
```

---

#### `DEVELOPMENT-PLAN.yaml`

**路径**：`.workflow-meta/DEVELOPMENT-PLAN.yaml`  
**创建者**：`meta-dm`

```yaml
project_id: "scope-pack-demo-01"
version: "1.0"
created_at: "2026-04-04T09:25:00Z"
waves:
  - wave: W1
    parallel: false
    stories:
      - story_id: STORY-001
        title: "实现 story-manager Agent"
        priority: P0
        assignee: meta-dev
        depends_on: []

  - wave: W2
    parallel: true       # 并行执行
    stories:
      - story_id: STORY-002
        title: "实现 create-story Skill"
        priority: P0
        assignee: meta-dev
        depends_on: [STORY-001]
      - story_id: STORY-003
        title: "实现 update-story-status Skill"
        priority: P0
        assignee: meta-dev
        depends_on: [STORY-001]
```

---

### 5.6 验证与交付文件

#### `VALIDATION-ENV.yaml`

**路径**：`.workflow-meta/VALIDATION-ENV.yaml`  
**提供者**：**人工**（检查点4 时由用户填写或确认）  
**meta-qa 在此文件不存在时拒绝进入验证阶段**

```yaml
environment_id: "local-claude-code"
provided_by: human
targets:
  - claude-code
  - copilot
runtime:
  python: "3.11"
  node: "20.x"
required_paths:
  - ".claude/agents/"
  - ".github/copilot/"
credentials:
  provided: false
  notes: "本轮不涉及 API 调用，无需密钥"
approval:
  confirmed: true
  confirmed_by: "user"
  confirmed_at: "2026-04-04T10:00:00Z"
notes:
  - "只验证安装目录结构和文件引用"
  - "不执行实际 Agent 调用"
```

---

#### `VERIFICATION-REPORT.md`

**路径**：`.workflow-meta/VERIFICATION-REPORT.md`  
**创建者**：`meta-qa`  
**8 维度验收**：每维度结论为 `PASS` / `WARN` / `FAIL`

```markdown
---
version: "1.0"
created_at: "2026-04-04T10:30:00Z"
---

## Story 验证汇总

| Story ID  | 完整性 | 平台适配 | 标准覆盖 | 安全合规 | 命名规范 | Frontmatter | 可安装性 | 文档覆盖 | 结论 |
|-----------|--------|---------|---------|---------|---------|-------------|---------|---------|------|
| STORY-001 | PASS   | PASS    | PASS    | PASS    | PASS    | PASS        | PASS    | WARN    | PASS |
| STORY-002 | PASS   | PASS    | PASS    | PASS    | PASS    | PASS        | PASS    | PASS    | PASS |

## 安全扫描摘要

- 危险命令：0 项
- Prompt 注入风险：0 项

## 未通过项（BLOCKING）

无

## 结论

**整体结论**：PASS，可进入打包阶段。
```

---

#### `PACKAGE-MANIFEST.yaml`

**路径**：`.workflow-meta/PACKAGE-MANIFEST.yaml`  
**创建者**：`meta-qa`（打包完成后）  
**包含 SHA256** 用于完整性校验

```yaml
version: "1.0"
project_id: "scope-pack-demo-01"
generated_at: "2026-04-04T11:00:00Z"
targets:
  - platform: copilot
    install_path: ".github/copilot/"
    entry_file: "copilot-instructions.md"
    artifacts:
      - file: "skills/story-manager.md"
        sha256: "a1b2c3d4..."
  - platform: claude-code
    install_path: ".claude/"
    entry_file: "CLAUDE.md"
    artifacts:
      - file: "agents/story-manager.md"
        sha256: "e5f6g7h8..."
      - file: "skills/create-story.md"
        sha256: "i9j0k1l2..."
```

---

### 5.7 变更管理文件

#### `changes/CR-NNN.md`

**路径**：`.workflow-meta/changes/CR-001.md`  
**创建者**：`meta-po`（收到变更请求后，调用 `change-impact-analysis` Skill）  
**5 维度影响分析**：需求层 / 设计层 / Story 层 / 安全层 / 交付层

```markdown
---
cr_id: "CR-001"
status: "approved"
impact_level: "medium"
created_at: "2026-04-04T10:15:00Z"
created_by: "meta-po"
approved_by: "user"
approved_at: "2026-04-04T10:20:00Z"
---

## 变更描述
新增对 OpenClaw 平台的支持。

## 五维度影响分析

| 维度   | 受影响对象             | 影响程度 | 处理方式           |
|--------|----------------------|---------|-------------------|
| 需求层 | R001 目标平台描述     | 低      | 追加"openclaw"    |
| 设计层 | ARCHITECTURE-DECISION | 中      | 新增 OpenClaw 条目 |
| Story 层 | 新增 STORY-005      | 中      | 加入 Wave 3       |
| 安全层 | 无                   | 无      | —                 |
| 交付层 | PACKAGE-MANIFEST     | 低      | 新增 openclaw 块  |

## 回退决策
- 影响范围：局部
- 回退到阶段：story-planning
- 需要重新确认的对象：STORY-BACKLOG.md
```

---

### 5.8 文件生命周期总览

| 文件 | 创建阶段 | 创建者 | 最后修改阶段 | 是否人工确认 |
|------|---------|--------|------------|------------|
| `REQUEST.md` | init | meta-po | init | 否 |
| `CLARIFICATION-LOG.md` | requirement-clarification | meta-pm | requirement-clarification | 否（自动追加）|
| `REQUIREMENTS.md` | requirement-clarification | meta-pm | requirement-clarification | **是（检查点1）** |
| `SOLUTION-DESIGN.md` | solution-design | meta-se | solution-design | **是（检查点2）** |
| `ARCHITECTURE-DECISION.md` | solution-design | meta-se | solution-design | **是（检查点2）** |
| `STORY-BACKLOG.md` | story-planning | meta-dm | story-planning | **是（检查点3）** |
| `DEVELOPMENT-PLAN.yaml` | story-planning | meta-dm | story-planning | 否 |
| `stories/STORY-*.md` | story-planning（结构）| meta-dm/meta-dev | story-development | 否 |
| `STORY-STATUS.md` | story-planning | meta-dm | story-development（持续）| 否（自动更新）|
| `VALIDATION-ENV.yaml` | verification 前 | **人工** | — | **是（检查点4）** |
| `VERIFICATION-REPORT.md` | verification | meta-qa | verification | 否 |
| `PACKAGE-MANIFEST.yaml` | packaging | meta-qa | packaging | 否 |
| `changes/CR-*.md` | 任意阶段（变更时）| meta-po | 变更处理后 | **是（中/高风险）** |
| `STATE.md` | init | meta-po | 每轮结束 | 否（系统维护）|
