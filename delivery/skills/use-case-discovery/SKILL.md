---
name: use-case-discovery
description: >-
  当需要与用户系统化讨论使用场景、生成或增量更新 `process/USE-CASES.md` 时使用。
  触发词包括：场景发现、使用场景讨论、用户场景梳理、use-case workshop、use case discovery。
  适用场景：meta-pm 完成阶段零调研后进入场景发现，或已有 USE-CASES 草稿 / 确认稿需要恢复、评审与更新时。
argument-hint: "可选：用户本轮补充的场景描述、粘贴的现有用户故事 / PRD 文本"
user-invokable: true
status: active
called-by: meta-pm
output: process/USE-CASES.md
---

## 目标

与用户共同完成**产物类型感知**的渐进式场景发现：先锁定当前工作模式、场景主体和交付出口，再通过轻量头脑风暴判定目标交付形态与治理方式，随后建立基线场景并做 8 维覆盖扫描，最终生成或更新标准化 `USE-CASES.md`，并在 Phase 3 追加场景发现摘要到 `CLARIFICATION-LOG.md`。

## 适用场景

- meta-pm 已完成阶段零快速调研，准备进入正式场景发现
- 用户粘贴了已有用户故事 / PRD 文本，希望先导入为场景基线再校准
- 已存在 `process/USE-CASES.md`，需要从 draft 恢复继续，或对 confirmed 版本做增量更新
- 需要先判断目标交付是 tool / skill / agent / workflow / mixed，再决定场景发现的治理标签

## 前置条件

- [ ] `process/REQUEST.md` 已存在且非空
- [ ] 当前任务目标是发现 / 确认使用场景，而不是直接提取需求或展开测试覆盖

## 必须读取的输入

| 输入 | 必须性 | 用途 |
|---|---|---|
| `process/REQUEST.md` | 必须 | 场景发现的原始起点 |
| `process/INPUT-INDEX.md` | 可选 | 定位原始材料与可导入背景 |
| `process/CLARIFICATION-LOG.md` | 可选 | 读取阶段零调研结论，并在 Phase 3 追加场景发现摘要 |
| `process/USE-CASES.md` | 可选 | draft 恢复或 confirmed 更新的唯一真相源 |
| `process/changes/CR-*.md` | 条件必须 | 若本轮为变更触发，读取文档处理决策与旧基线映射 |
| 用户本轮新增输入 | 可选 | 新场景、补充说明、或 Phase 0 粘贴文本 |
| 目标平台 / 安装约束 | 可选 | 辅助判断产物类型、交付边界与治理方式 |

## 知识来源

- `templates/USE-CASES-TEMPLATE.md`：`USE-CASES.md` 的内容契约
- `references/8-dimensions-framework.md`：Phase 2 的详细扫描框架（按需加载）
- `agents/meta-pm.md`：上游编排方定义的 `USE-CASES.md` 结构规范与衔接规则

## 执行步骤

### 步骤 0：启动校验与恢复模式判定

1. 读取 `REQUEST.md`；若缺失或为空，立即终止并提示先完成初始化。
2. 若存在 `USE-CASES.md status: draft`，默认进入**恢复模式**，继续完善已有草稿。
3. 若存在 `USE-CASES.md status: confirmed`，仅在用户明确要求修改时进入**更新模式**；更新后必须递增 `version`，禁止静默覆盖。
4. 若本轮为 CR 触发，必须读取 CR 中的文档处理决策；未明确允许归档或新建时，默认进入**增量更新模式**。
5. 若进入更新模式，必须保留旧场景基线，追加或标注变更，并在 `## 修订记录` 中写入版本、日期、修订人、变更要点、文档处理方式。
6. 若存在 `CLARIFICATION-LOG.md`，只读历史；后续仅追加，不覆盖。
7. 若已有草稿包含 `engagement_mode`、`scenario_subject_type`、`scenario_subject_id`、`target_artifact_type`、`governance_mode`、`review_policy`，恢复时优先沿用；仅在用户目标明显变化时重判。
8. 若用户**未显式说明**“当前是在做 meta 工作流自我开发 / 优化 / 整改”，默认：
   - `engagement_mode = production`
   - `scenario_subject_type = target-artifact`
   - 交付出口不得默认为当前仓库 `delivery/`
9. 仅当用户明确表达“这是 meta 工作流优化 / 自我开发 / 整改 meta 工作流本身”时，才切换为：
   - `engagement_mode = meta-self-dev`
   - `scenario_subject_type = implementation-carrier`
   - 允许交付出口使用当前仓库 `delivery/`
10. 在 `production` 模式下，必须扫描目标项目 `README.md` / `README.*` / `docs/` 中的交付物、发布、构建或包结构说明；若存在，按其记录 `delivery_routing`；若不存在，输出建议目录并等待用户确认，不得直接写当前仓库 `delivery/`。

### 步骤 1：Phase 0（可选）导入模式

1. 仅当用户**粘贴文本**形式提供现有用户故事、PRD 或需求片段时启用。
2. 将导入内容解析为画像、成功指标与场景雏形，作为 Phase 1A / 1B 的基线，不直接视为已确认场景。
3. 导入失败时跳过，不得阻塞后续 Phase 1A。

### 步骤 2：Phase 1A 目标产物与治理方式判定

1. 先锁定模式字段：
   - `engagement_mode`：`production / meta-self-dev`
   - `scenario_subject_type`：`target-artifact / implementation-carrier`
   - `scenario_subject_id`：目标产物 ID 或当前实现载体 ID
2. 先锁定交付出口字段：
   - `delivery_routing.mode`：`meta-flow-delivery / project-readme-contract / proposed-output`
   - `delivery_routing.output_root`：已确认输出根目录；未确认时必须留空
   - `delivery_routing.source`：`meta-self-dev / README / docs / user-confirmed`
3. 若用户没有显式声明 meta 优化，**不得**把当前仓库 / 当前工作流视为默认场景主体。
4. 在 `production` 模式下，若请求同时出现“整改当前仓库”和“目标 Agent/Skill/Workflow”，优先把目标产物作为场景主体，当前仓库仅视为实现载体。
5. 若目标形态、场景主体或交付出口不清，进入轻量头脑风暴子流程：
   - 一次只问 1 个问题，避免一次性抛出长问卷；
   - 至少提出 2 个候选交付形态或输出路径，并给出 trade-off；
   - 若只有 1 个合理方案，必须写明无备选原因；
   - 用户分段确认后再进入 8 维扫描。
6. 再判定当前请求的目标交付类型：`tool / skill / agent / workflow / mixed`。
7. 仅在必要时追问以下最小问题：交付对象是什么、谁触发、主要文件/目录落点在哪、是否存在多个不同交付面。
8. 同步确定治理字段：
   - `target_artifact_type`
   - `governance_mode`：`direct / review-gated / conditional`
   - `review_policy`：`none / light / strict`
9. `mixed` 只能在以下任一硬规则成立时输出：
   - 同一请求同时要求 **2 类以上不同交付形态**，且它们的主要落盘位置或安装位置不同；
   - 同一请求同时包含 **不同触发方式**（例如交互式对话 + 后台自动执行）；
   - 同一请求需要经过 **不同下游链路**（例如一个走 Agent 实现，一个走 Workflow 编排）。
10. 若无法判定为单一类型且未命中 `mixed` 硬规则，继续追问；不得凭感觉落 `mixed`。

### 步骤 3：Phase 1B 基线场景发现

1. 以 PM 三问开场：**谁在使用 / 解决什么问题 / 如何量化成功**。
2. 再用 5W1H 追问每个候选场景：触发条件、输入、处理逻辑、输出/结果、前置条件、排除情况。
3. 每完成一轮基线整理，就按模板**增量写入** `process/USE-CASES.md`，状态保持 `draft`。
4. Phase 1B 只建立场景基线，不做 8 维分析。

### 步骤 4：Phase 2 八维覆盖扫描

1. 按需加载 `references/8-dimensions-framework.md`。
2. 先询问是否需要追加会话级自定义维度；软性上限 ≤ 2 个。
3. 按默认 8 维 + 自定义维度逐项扫描，每轮最多追问 3 个遗漏维度。
4. 每个维度都必须落到以下状态之一：`已覆盖 / 已补充 / 不适用 / 待调研`。
5. 每轮补充后都要把 `USE-CASES.md` 增量回写为 `draft`，不得只停留在会话内存。

### 步骤 5：Phase 3 确认与输出

1. 结构化展示全量场景、治理字段与覆盖自检表，使用固定选项让调用方确认：
   - `✅ 确认通过`
   - `❌ 确认不通过`
   - `✏️ 需要补充 / 修改`
2. `✅`：将 `USE-CASES.md` 标记为 `confirmed`；若是更新模式，递增 `version`。
3. `❌` 或 `✏️`：记录修改建议，保持或回退到 `draft`，并根据修改类型返回 Phase 1 或 Phase 2。
4. 在 Phase 3 退出时，向 `CLARIFICATION-LOG.md` 追加**场景发现摘要**；若日志不存在，则按标准模板初始化后再追加。
5. 若是更新模式，检查 `## 修订记录` 与 CR 旧基线映射均已落地；缺失时不得返回 `confirmed`。
6. 返回结构化完成摘要，至少包含：

```yaml
use_cases_path: process/USE-CASES.md
status: draft | confirmed
version: "x.y"
mode: create | resume | update
engagement_mode: production | meta-self-dev
scenario_subject_type: target-artifact | implementation-carrier
scenario_subject_id: "<artifact-id or repo-id>"
target_artifact_type: tool | skill | agent | workflow | mixed
governance_mode: direct | review-gated | conditional
review_policy: none | light | strict
delivery_routing:
  mode: meta-flow-delivery | project-readme-contract | proposed-output
  output_root: "<confirmed output root or empty>"
  source: meta-self-dev | README | docs | user-confirmed
clarification_log_appended: true
next_input_hint: "继续补充场景 / 转入 requirement-extraction / 等待用户确认"
```

## 输出文件 / 输出模板

| 文件 | 路径 | 角色 |
|---|---|---|
| 场景工件 | `process/USE-CASES.md` | 主输出；Phase 1/2 持续写 draft，Phase 3 可确认 |
| 场景发现摘要 | `process/CLARIFICATION-LOG.md` | Phase 3 追加式日志 |
| 模板 | `skills/use-case-discovery/templates/USE-CASES-TEMPLATE.md` | 渲染基线 |

## 约束

- `USE-CASES.md` 必须与 `agents/meta-pm.md` 的字段契约逐项一致
- Phase 1A / 1B 与 Phase 2 都必须增量写入 `draft`，不得只在确认时一次性落盘
- 对已确认的 `USE-CASES.md` 只能进入更新模式，必须显式保留版本演进
- CR 触发的更新必须保留旧场景基线，并追加 `## 修订记录`；不得用新草案整体替换旧文档
- 删除或归档旧场景只能在 CR 明确批准时执行，且必须在 CR 中保留完整摘录和映射关系
- 若用户未显式声明 meta 工作流优化 / 自我开发，必须默认 `engagement_mode=production` 且 `scenario_subject_type=target-artifact`
- 在 `production` 模式下，`USE-CASES.md` 不得把当前仓库整改者 / workflow 维护者写成默认 Persona，除非用户明确说明他们就是目标用户
- 在 `production` 模式下，未发现 README/docs 交付约定时，必须先提出建议并等待用户确认；确认前不得创建 `delivery/` 交付件
- 本 Skill 不负责提取 `REQUIREMENTS.md`，也不负责测试场景展开或需求歧义清单
- 默认使用中文；仅在用户显式要求时切换英文
- 不得把 review gate 的执行细节写回本 Skill；这里只输出治理标签，不负责编排评审

## 验收标准

- [ ] `USE-CASES.md` 含完整 frontmatter、模式字段、治理字段、画像、成功指标、排除项、场景列表与覆盖自检表
- [ ] 每个场景都具备 7 个必填字段：角色、触发条件、输入、处理逻辑、输出/结果、前置条件、排除情况
- [ ] 默认 8 维全部被处理，未适用项已显式标注理由
- [ ] draft 可恢复，confirmed 不会被静默覆盖
- [ ] 更新模式下 `## 修订记录` 已追加，旧场景基线可追溯
- [ ] `target_artifact_type` / `governance_mode` / `review_policy` 语义明确且可被上下游直接消费
- [ ] `delivery_routing` 已记录交付出口来源；production 模式下不默认写当前仓库 `delivery/`
- [ ] Phase 3 返回结构化完成摘要，并已向 `CLARIFICATION-LOG.md` 追加摘要

## 不适用边界

- 当前目标是从已确认场景中提取需求条目 → 转给 `requirement-extraction`
- 当前目标是识别需求歧义、生成未决问题列表 → 转给 `requirement-clarifier`
- 当前目标是为需求设计测试覆盖 / 测试矩阵 → 转给 `scenario-expansion`
- 当前目标是定义 review gate 执行规则或 LLD 写作方法 → 转给相邻设计对象

## Gotchas

- **Never skip Phase 1A / 1B**：即使用户粘贴现成材料，也必须先判定交付形态，再补齐画像与成功指标基线
- **头脑风暴不是长问卷**：目标不清时一次只问一个问题，先给 2-3 个候选方案和 trade-off，再让用户分段确认
- **维度不能静默跳过**：每个维度至少标成已覆盖 / 已补充 / 不适用 / 待调研之一
- **不要替用户补答案**：追问一次仍无结论时，可记为“待调研”，不能脑补
- **draft 文件是恢复唯一真相源**：恢复依赖 `USE-CASES.md`，不是会话记忆
- **confirmed 只能更新，不能覆盖**：进入更新模式后再确认，并递增版本
- **更新不是重写**：CR 场景变更必须保留旧 UC-* 语义，新增或修改内容要能回链到旧基线
- **不要越界到需求提取**：场景里出现“应该支持 X”时，仍只记录为场景内容
- **`mixed` 不是兜底桶**：只有命中三条硬规则之一时才可使用，否则继续追问
- **治理字段只负责打标签**：`governance_mode` 和 `review_policy` 用于下游路由，不在本 Skill 内执行评审
- **默认是 production，不是 meta-self-dev**：只有用户明确说“meta 工作流优化 / 自我开发”时，才允许把当前仓库 / 当前工作流当成场景主体
- **delivery/ 不是 production 默认出口**：只有 meta-flow 自身改进才默认写当前仓库 `delivery/`；外部项目必须先读 README/docs 或获得用户确认
