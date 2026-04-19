# SCOPE-Pack Template 整改方案（第二版：取消根 templates 目录）

## 1. 修订说明

本次修订覆盖第一轮“保留根 `templates/` 目录”的方案，新的目标是：

1. **不保留仓库根 `templates/` 目录**；
2. **meta-agent 不直接引用模板路径**；
3. 模板只归属于**拥有该正式工件结构的 Skill**；
4. 多 Skill 共享同一正式工件时，以**单一 Skill 持有模板**、其他 Skill 依赖内容契约为原则；
5. Agent 与 Skill 的应用关系统一记录到 `skills/README.md`，不再通过共享模板目录承载 Agent ↔ Skill 关系。

> 本方案是对第一轮“目录搬迁整改”的**第二轮收缩**：不是回退治理，而是进一步消除“根共享模板目录 + Agent 直接引用模板”的设计冗余。

---

## 2. 核心判断

### 2.1 为什么取消根 `templates/`

第一轮整改解决了旧 `agents/templates/` 混放问题，但仍保留了“根共享模板目录”这一层。复盘后发现：

1. 很多模板实际上只有**一个 Skill 真正拥有**；
2. 把 Agent 记为模板引用方，会夸大“共享模板”的范围；
3. 多个 Skill 作用于同一正式文档时，常见情况是“一个生成、一个归一化/校验”，并不需要共享模板目录；
4. `github/awesome-copilot` 这类仓库也说明：Agent/Skill 仓库不必默认带根共享模板目录。

因此，新的治理原则是：**模板归 Skill 所有，契约归文档对象所有，Agent 只编排不持有模板路径。**

### 2.2 Agent 是否应该引用模板

不应该。

Agent 的职责应是：

- 判断阶段是否可推进；
- 唤醒合适的 Skill；
- 检查上游输出对象是否完整；
- 发起人工检查点；
- 回写状态。

Agent 不应：

- 直接写模板路径；
- 依赖模板文件存在作为运行前提；
- 与 Skill 共同声明同一个模板所有权。

### 2.3 `solution-designer` 与 `hld-designer` 功能重叠评估

经逐项比对，两者在以下 6 个维度**完全一致**：

| 维度 | `hld-designer` | `solution-designer` | 结论 |
|------|----------------|---------------------|------|
| 前置条件 | REQUIREMENTS.md + USE-CASES.md 已确认 | 相同 | 一致 |
| 输入 | REQUIREMENTS.md, USE-CASES.md, REQUEST.md | 相同 | 一致 |
| 输出 | `.output/doc/HLD.md` | 相同 | 一致 |
| 模板 | `skills/hld-designer/templates/HLD-TEMPLATE.md` | 不再单独持有模板，复用 `hld-designer` 输出契约 | 一致 |
| 执行步骤 | 问题定义 → ≥2 候选方案 → 对比 → 推荐 → 写 HLD → 停在确认前 | 相同 | 一致 |
| 验收标准 | ≥2 候选方案 + 推荐 + 风险 | 与 hld-designer 输出口径一致 | 一致 |

唯一差异是触发词：`solution-designer` 额外覆盖"方案设计、架构设计、复杂度判定"等历史触发词。

**结论：合并。** 将 `solution-designer` 的触发词合入 `hld-designer`，`solution-designer` 标记为 `status: deprecated`，SKILL.md 改为重定向说明。

### 2.4 多个 Skill 作用于同一文档，是否必须合并

不一定。

只有在以下条件同时满足时，才应合并或别名化：

1. 同一阶段；
2. 同一触发语义；
3. 同一输出对象；
4. 同一验收口径；
5. 其中一个只是兼容入口。

按此标准：

- `solution-designer` → 合并入 `hld-designer`（见 §2.3）；
- `requirement-extraction` + `scope-normalization` → 不合并，一个生成、一个归一化；
- `change-impact-analysis` + `issue-routing` → 不合并，前者拥有 CR 模板，后者只消费 CR 内容契约。

---

## 3. 新治理原则

### 3.1 模板归属原则

| 判定条件 | 目标位置 |
|---|---|
| 某正式工件由单一 Skill 初始化或渲染 | `skills/<skill-name>/templates/` |
| 其他 Skill 仅消费该工件内容 | 不引用模板路径，只依赖输出对象契约 |
| 没有 Skill 拥有、仅 Agent 需要结构约束（≤30 行） | 内联到 Agent 提示词，不保留独立模板文件 |
| 没有 Skill 拥有、仅 Agent 需要结构约束（>30 行） | 保留为 Agent 提示词内的精简结构描述（关键章节 + 字段清单），不完整内联 |

### 3.2 Agent 引用原则

1. Agent 只声明**输出对象**，不声明模板路径。
2. Agent 只声明“调用哪个 Skill”，不声明“该 Skill 用哪个模板文件”。
3. Agent 与 Skill 的应用关系记录在 `skills/README.md`，不再通过模板登记表维护。

### 3.3 文档契约原则

1. 模板存在的目的，是约束**正式工件结构**，而不是提供共享目录。
2. 正式工件的 canonical owner 必须唯一。
3. 消费者 Skill 读取的是 `.output/...` 里的正式文档，不是模板文件。
4. 若某模板不再有明确的 Skill owner，应删除模板文件并把结构内联到规范中。

---

## 4. 目标目录结构

```text
skills/
  README.md                               # Agent ↔ Skill 应用关系 + 模板交叉引用

  requirement-clarifier/
    SKILL.md
    templates/
      CLARIFICATION-LOG-TEMPLATE.md

  requirement-extraction/
    SKILL.md
    templates/
      REQUIREMENTS-TEMPLATE.md

  state-router/
    SKILL.md
    templates/
      STATE-TEMPLATE.md

  hld-designer/
    SKILL.md
    templates/
      HLD-TEMPLATE.md

  story-manager/
    SKILL.md
    templates/
      STORY-TEMPLATE.md
      STORY-STATUS-TEMPLATE.md

  lld-designer/
    SKILL.md
    templates/
      STORY-LLD-TEMPLATE.md

  change-impact-analysis/
    SKILL.md
    templates/
      CR-TEMPLATE.md

  issue-drafter/
    SKILL.md
    templates/
      ISSUE-TEMPLATE.md

  run-feedback-parser/
    SKILL.md
    templates/
      RUN-EXEC-TEMPLATE.md

  workflow-renderer/
    SKILL.md
    templates/
      OUTPUT-TEMPLATE.md

  context-manifest-builder/
    SKILL.md
    templates/
      CONTEXT-MANIFEST-TEMPLATE.yaml

  solution-designer/
    SKILL.md                              # status: deprecated，重定向到 hld-designer

```

说明：

- `solution-designer` 标记为 `deprecated`，触发词合入 `hld-designer`，不再拥有独立模板；
- Agent 直接生成、且无真实 Skill owner 的文档（`REQUEST.md`、`INPUT-INDEX.md`、`USE-CASES.md`、`ARCHITECTURE-DECISION.md`、`STORY-BACKLOG.md`、`DEVELOPMENT-PLAN.yaml`、`TEST-STRATEGY.md`、`VALIDATION-ENV.yaml`、`INSTALL-MANIFEST.yaml`、`VERIFICATION-REPORT.md`、`FINAL-REVIEW-CHECKLIST.md`）改为 Agent 提示词内精简结构描述，不保留独立模板文件；
- 根 `templates/` 目录在整改完成后应被删除（含 `templates/README.md`）。

---

## 5. 模板迁移矩阵（第二版）

| 当前文件 | 新目标 | 所有权归属 | 行数 | 处理结论 |
|---|---|---|---|---|
| `templates/README.md` | 治理关系迁入 `skills/README.md` 新增章节 | 无（删除） | 34 | 交叉引用信息迁入 `skills/README.md`，原文件删除 |
| `templates/ARCHITECTURE-DECISION-TEMPLATE.md` | 删除独立模板，结构内联到 `meta-se` | Agent 内联 | 32 | `ARCHITECTURE-DECISION.md` 当前由 `meta-se` 直接产出，不交由 Skill 持有模板 |
| `templates/CLARIFICATION-LOG-TEMPLATE.md` | `skills/requirement-clarifier/templates/CLARIFICATION-LOG-TEMPLATE.md` | `requirement-clarifier` | 29 | 下沉为 Skill 私有模板 |
| `templates/CR-TEMPLATE.md` | `skills/change-impact-analysis/templates/CR-TEMPLATE.md` | `change-impact-analysis` | 48 | 下沉为 Skill 私有模板 |
| `templates/DEVELOPMENT-PLAN-TEMPLATE.yaml` | 删除独立模板，结构内联到 `meta-se` | Agent 内联 | 14 | `DEVELOPMENT-PLAN.yaml` 当前由 `meta-se` 直接产出，不交由 `wave-planner` 持有模板 |
| `templates/FINAL-REVIEW-CHECKLIST.md` | 删除独立模板，精简结构描述内联到 `meta-po` | Agent 内联 | 140 | 内联关键章节清单与必检字段，不完整嵌入 |
| `templates/HLD-TEMPLATE.md` | `skills/hld-designer/templates/HLD-TEMPLATE.md` | `hld-designer` | 315 | 下沉为 Skill 私有模板 |
| `templates/INPUT-INDEX-TEMPLATE.md` | 删除独立模板，结构内联到 `meta-po` | Agent 内联 | 38 | 内联关键结构描述 |
| `templates/INSTALL-MANIFEST-TEMPLATE.yaml` | 删除独立模板，结构内联到 `meta-qa` | Agent 内联 | 17 | `package-builder` 只消费安装清单内容并生成安装脚本，不拥有模板 |
| `templates/REQUEST-TEMPLATE.md` | 删除独立模板，结构内联到 `meta-po` | Agent 内联 | 24 | 内联到 Agent（≤30 行，可完整嵌入） |
| `templates/REQUIREMENTS-TEMPLATE.md` | `skills/requirement-extraction/templates/REQUIREMENTS-TEMPLATE.md` | `requirement-extraction` | 54 | 下沉为 Skill 私有模板 |
| `templates/STATE-TEMPLATE.md` | `skills/state-router/templates/STATE-TEMPLATE.md` | `state-router` | 42 | 下沉为 Skill 私有模板 |
| `templates/STORY-BACKLOG-TEMPLATE.md` | 删除独立模板，结构内联到 `meta-se` | Agent 内联 | 20 | `STORY-BACKLOG.md` 当前由 `meta-se` 直接产出，`story-manager` 不直接拥有该模板 |
| `templates/STORY-LLD-TEMPLATE.md` | `skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` | `lld-designer` | 119 | 下沉为 Skill 私有模板 |
| `templates/STORY-TEMPLATE.md` | `skills/story-manager/templates/STORY-TEMPLATE.md` | `story-manager` | 74 | 下沉为 Skill 私有模板 |
| `templates/TEST-STRATEGY-TEMPLATE.md` | 删除独立模板，精简结构描述内联到 `meta-qa` | Agent 内联 | 62 | `meta-qa` 已有部分内联结构，补充关键章节清单 |
| `templates/USE-CASES-TEMPLATE.md` | 删除独立模板，精简结构描述内联到 `meta-pm` | Agent 内联 | 54 | 内联关键章节清单与字段要求 |
| `templates/VALIDATION-ENV-TEMPLATE.yaml` | 删除独立模板，结构内联到 `meta-qa` | Agent 内联 | 15 | 内联到 Agent（≤30 行，可完整嵌入） |
| `templates/VERIFICATION-REPORT-TEMPLATE.md` | 删除独立模板，结构内联到 `meta-qa` | Agent 内联 | 17 | 内联到 Agent（≤30 行，可完整嵌入） |

> 已存在的 `ISSUE-TEMPLATE.md`、`RUN-EXEC-TEMPLATE.md`、`OUTPUT-TEMPLATE.md`、`CONTEXT-MANIFEST-TEMPLATE.yaml`、`STORY-STATUS-TEMPLATE.md` 保持 Skill 私有，不在迁移范围内。

---

## 6. Skill 整改要求

### 6.1 需要继续保留模板路径的 Skill

这些 Skill 是正式工件的 canonical owner，应在 `SKILL.md` 中继续显式引用自己的私有模板：

- `requirement-clarifier` — `CLARIFICATION-LOG-TEMPLATE.md`
- `requirement-extraction` — `REQUIREMENTS-TEMPLATE.md`
- `state-router` — `STATE-TEMPLATE.md`
- `hld-designer` — `HLD-TEMPLATE.md`
- `story-manager` — `STORY-TEMPLATE.md`、`STORY-STATUS-TEMPLATE.md`
- `lld-designer` — `STORY-LLD-TEMPLATE.md`
- `change-impact-analysis` — `CR-TEMPLATE.md`
- `issue-drafter` — `ISSUE-TEMPLATE.md`
- `run-feedback-parser` — `RUN-EXEC-TEMPLATE.md`
- `workflow-renderer` — `OUTPUT-TEMPLATE.md`
- `context-manifest-builder` — `CONTEXT-MANIFEST-TEMPLATE.yaml`

**路径更新要求**：所有引用旧路径 `templates/XXX` 的 SKILL.md 必须改为 `skills/<skill-name>/templates/XXX`。受影响 Skill 及引用处数量：

| Skill | 需更新路径引用数 | 涉及行号 |
|---|---|---|
| `state-router` | 9 处 | 14, 24, 30, 46, 54, 87, 94, 99, 112 |
| `requirement-extraction` | 4 处 | 14, 37, 52, 56 |
| `hld-designer` | 3 处 | 36, 50, 54 |
| `lld-designer` | 2 处 | 35, 49 |
| `story-manager` | 2 处 | 34, 49 |
| `requirement-clarifier` | 2 处 | 36, 50 |
| `change-impact-analysis` | 2 处 | 36, 52 |

### 6.2 只消费内容契约、不引用模板的 Skill

以下 Skill 只能消费正式文档，不再引用模板路径：

- `solution-designer`（已废弃，重定向到 `hld-designer`）
- `scenario-expansion`
- `scope-normalization`
- `issue-routing`（SKILL.md line 36 引用 `templates/CR-TEMPLATE.md`，需删除该路径引用，改为依赖 `.output/changes/CR-*.md` 内容契约）
- `coverage-checker`
- `dangerous-command-scan`
- `package-builder`
- `platform-validator`
- `runtime-risk-review`
- `permission-boundary-check`
- `context-handoff`

### 6.3 `solution-designer` 合并与废弃

1. `solution-designer` 的触发词（方案设计、架构设计、复杂度判定、设计方案、simple/standard/complex 判断）合入 `hld-designer` 的 `description` 字段；
2. `solution-designer/SKILL.md` 的 `status` 改为 `deprecated`，正文替换为重定向说明；
3. `skills/README.md`：
   - line 18：从 `meta-se` 的 Skill 列表中移除 `solution-designer`；
   - line 37：标注为"已废弃，重定向到 hld-designer"；
4. `rules/copilot-instructions.md` line 26 和 `rules/CLAUDE.md` line 26：删除 `solution-designer` 行，触发词合入 `hld-designer` 行；
5. `docs/AGENT-SKILL-REFERENCE.md` line 100：标注 `deprecated`，说明已合入 `hld-designer`；
6. 确认 `agents/meta-se.md` Skill 编排合约中无 `solution-designer` 引用（当前已不含，无需修改）。

---

## 7. Agent 整改要求

1. 删除以下 Agent 中的模板路径引用：
   - `meta-dm.md` line 38：`templates/STORY-TEMPLATE.md`
   - `meta-qa.md` line 44：`templates/VALIDATION-ENV-TEMPLATE.yaml`
2. 其他 Agent 不再新增模板路径引用；
3. Agent 提示词若需要文档结构要求，按以下策略处理：
   - ≤30 行的模板（`REQUEST-TEMPLATE`、`VALIDATION-ENV-TEMPLATE`、`VERIFICATION-REPORT-TEMPLATE`）：可完整内联为结构描述；
   - >30 行的模板（`FINAL-REVIEW-CHECKLIST` 140 行、`TEST-STRATEGY-TEMPLATE` 62 行、`USE-CASES-TEMPLATE` 54 行、`INPUT-INDEX-TEMPLATE` 38 行）：只内联关键章节清单与必填字段说明，不完整嵌入模板全文；
4. 确认 `meta-se` Skill 编排合约中无 `solution-designer` 引用（当前已不含，无需修改）；
5. Agent 与 Skill 的应用关系统一登记在 `skills/README.md`；
6. `docs/AGENT-SKILL-REFERENCE.md` 只描述当前正式交付的 Skill，不为历史占位 Skill 背书。

---

## 8. 安装脚本与文档整改要求

### 8.1 安装脚本

1. `scripts/install.py` 删除 `install_shared_templates()` 函数及其调用；
2. 删除 `shared_templates_dir` 字段及所有引用（约 16 处）；
3. 安装时只复制 `skills/<skill-name>/templates/`（已有 `install_skill_private_templates()` 函数）。

### 8.2 规则文件（`rules/` 目录）

以下文件需同步修改：

| 文件 | 修改内容 |
|---|---|
| `rules/AGENTS.md` | 删除 `templates/` 共享模板目录行，并将旧的 `templates/README.md` 维护规则改为同步更新 `skills/README.md` |
| `rules/copilot-instructions.md` | 删除"共享模板：`templates/`"相关表述 |
| `rules/CLAUDE.md` | 删除"共享模板：`templates/`"相关表述 |

### 8.3 根目录文档

| 文件 | 修改内容 |
|---|---|
| `README.md` line 11 | 删除 `templates/` 共享模板目录行 |
| `README.md` line 78 | 从交付目录列表中删除 `- templates/` |
| `README.md` line 83 | 删除"共享模板从 `templates/` 安装"行 |
| `AGENTS.md` | 删除 `templates/` 共享模板目录行，并将旧的 `templates/README.md` 维护规则改为同步更新 `skills/README.md` |

### 8.4 关系登记表

- 与模板关系相关的文档，以 `skills/README.md` 为正式关系表；
- 若后续需要记录模板 owner / consumer 关系，可在 `skills/README.md` 增加对应章节；该章节不是本次整改的唯一完成条件。

### 8.5 `skills/README.md` 新增章节

若后续需要记录模板 owner / consumer 关系，可在现有"Skill → Canonical Agent 关系"表之后追加以下章节：

```markdown
## Skill 模板交叉引用

> 本章节记录 Skill 间因消费同一正式工件而产生的模板交叉引用关系。
> 消费者 Skill 不直接引用模板路径，只依赖产出 Skill 写入 `.output/` 的正式文档内容契约。

| 正式工件 | 模板持有 Skill | 消费者 Skill | 说明 |
|---|---|---|---|
| `HLD.md` | `hld-designer` | （无交叉引用） | `solution-designer` 已废弃 |
| `CR-*.md` | `change-impact-analysis` | `issue-routing` | issue-routing 消费 CR 内容契约 |
| `REQUIREMENTS.md` | `requirement-extraction` | `scope-normalization` | scope-normalization 归一化已生成的需求 |
| `CLARIFICATION-LOG.md` | `requirement-clarifier` | （无交叉引用） | |
| `STATE.md` | `state-router` | （无交叉引用） | |
| `STORY-*.md` | `story-manager` | （无交叉引用） | |
| `STORY-*-LLD.md` | `lld-designer` | （无交叉引用） | |
```

---

## 9. 执行顺序

1. 审计 `docs/AGENT-SKILL-REFERENCE.md`，确保它只反映当前已交付的 Agent / Skill。
2. 合并 `solution-designer` 到 `hld-designer`：
   a. 将 `solution-designer` 触发词合入 `hld-designer/SKILL.md` 的 `description`；
   b. 将 `solution-designer/SKILL.md` 标记为 `status: deprecated`，正文改为重定向说明；
   c. 确认 `agents/meta-se.md` Skill 编排合约无 `solution-designer` 引用（当前已不含，无需修改）。
3. 为需要下沉模板所有权的 Skill 建立或补齐 `templates/` 子目录：
   - `skills/requirement-clarifier/templates/CLARIFICATION-LOG-TEMPLATE.md`
   - `skills/requirement-extraction/templates/REQUIREMENTS-TEMPLATE.md`
   - `skills/state-router/templates/STATE-TEMPLATE.md`
   - `skills/hld-designer/templates/HLD-TEMPLATE.md`
   - `skills/lld-designer/templates/STORY-LLD-TEMPLATE.md`
   - `skills/change-impact-analysis/templates/CR-TEMPLATE.md`
4. 将根 `templates/` 下需保留的模板搬迁到对应 Skill 的 `templates/` 目录。
5. 逐 Skill 更新 `SKILL.md` 中的模板路径引用：
   - `templates/XXX` → `skills/<skill-name>/templates/XXX`
   - 受影响 Skill 及引用处数量：`state-router`(9处)、`requirement-extraction`(4处)、`hld-designer`(3处)、`lld-designer`(2处)、`story-manager`(2处)、`requirement-clarifier`(2处)、`change-impact-analysis`(2处)
   - `solution-designer`：删除模板路径引用（已废弃）
   - `issue-routing` line 36：删除 `templates/CR-TEMPLATE.md` 引用（消费者不引用模板路径）
6. 将没有 Skill owner 的模板删除，并把结构要求内联到 Agent 提示词（按 §7.3 策略处理大小模板）。
7. 删除 Agent 提示词中的模板路径引用：
   - `meta-dm.md` line 38
   - `meta-qa.md` line 44
8. 更新 `skills/README.md`：
   a. `solution-designer` 标注为已废弃，从 `meta-se` Skill 列表中移除；
   b. 新增"模板交叉引用"章节（见 §8.5）。
9. 更新规则文件：
   - `rules/AGENTS.md`：删除 line 66 模板目录行 + 替换 line 111 协议规则
   - `rules/copilot-instructions.md`：删除 line 55 共享模板行 + 删除 line 26 `solution-designer` 行（触发词合入 `hld-designer` 行）
   - `rules/CLAUDE.md`：删除 line 55 共享模板行 + 删除 line 26 `solution-designer` 行（触发词合入 `hld-designer` 行）
10. 更新根目录文档：
    - `AGENTS.md`：删除 line 66 + 替换 line 100 协议规则
    - `README.md`：删除 line 11 模板目录行 + 删除 line 78 交付目录列表中的 `templates/` + 删除 line 83 共享模板安装说明
    - `docs/AGENT-SKILL-REFERENCE.md` line 100：标注 `solution-designer` 为 `deprecated`
11. 更新安装脚本 `scripts/install.py`：删除 `install_shared_templates()` 函数、`shared_templates_dir` 字段及相关调用。
12. 删除根 `templates/` 目录（含 `README.md`）。
13. 全仓库回归验证（见 §10.9）。

---

## 10. 完成标准

整改完成后，应同时满足：

1. 仓库根**不存在** `templates/` 目录（含 `templates/README.md`）。
2. 不存在 Agent 直接引用模板路径的情况。
3. 所有保留的模板都位于 `skills/<skill-name>/templates/`。
4. 所有消费者 Skill 只依赖正式工件内容，不依赖模板路径。
5. `skills/README.md` 已包含"模板交叉引用"章节，且与当前 Skill 关系一致。
6. `docs/AGENT-SKILL-REFERENCE.md` 与当前交付 Agent / Skill 清单一致。
7. `solution-designer` 已标记为 `deprecated`，触发词已合入 `hld-designer`。
8. 以下文件已完成更新：
   - `scripts/install.py`：删除 `install_shared_templates()` 函数及 `shared_templates_dir` 字段
   - `README.md`：删除 line 11 模板目录行 + line 78 交付目录列表 + line 83 共享模板安装说明
   - `AGENTS.md`：删除 `templates/` 目录行 + 替换"模板映射维护"协议规则
   - `rules/AGENTS.md`：删除 `templates/` 目录行 + 替换协议规则
   - `rules/copilot-instructions.md`：删除"共享模板"行 + 删除 `solution-designer` 触发词行
   - `rules/CLAUDE.md`：删除"共享模板"行 + 删除 `solution-designer` 触发词行
   - `docs/AGENT-SKILL-REFERENCE.md`：`solution-designer` 标注 deprecated
   - `issue-routing/SKILL.md`：删除 `templates/CR-TEMPLATE.md` 路径引用

### 10.9 回归验证命令

```bash
# 1. 验证根 templates/ 已删除
test ! -d templates/ && echo "PASS: templates/ deleted" || echo "FAIL: templates/ still exists"

# 2. 验证无残留的根模板路径引用（排除本方案文档、docs/、.output/、.github/）
grep -rn "templates/" agents/ skills/ rules/ AGENTS.md README.md scripts/ \
  | grep -v "skills/.*/templates/" \
  | grep -v ".output/templates/" \
  | grep -v "docs/" \
  | grep -v ".github/" \
  && echo "FAIL: residual root template references found" \
  || echo "PASS: no residual root template references"

# 3. 验证所有 Skill 私有模板文件存在
for skill_dir in skills/*/templates; do
  [ -d "$skill_dir" ] && for f in "$skill_dir"/*; do
    [ -f "$f" ] && echo "OK: $f" || echo "MISSING: $f"
  done
done

# 4. 验证 solution-designer 已标记 deprecated
grep -q "status: deprecated" skills/solution-designer/SKILL.md \
  && echo "PASS: solution-designer deprecated" \
  || echo "FAIL: solution-designer not deprecated"

# 5. 验证 install.py 无共享模板函数
grep -q "install_shared_templates" scripts/install.py \
  && echo "FAIL: install_shared_templates still exists" \
  || echo "PASS: install_shared_templates removed"
```

---

## 11. 迁移后约束

1. **不得重建根 `templates/` 目录**——如需新增模板，必须选定 owner Skill 并放入其 `templates/` 子目录。
2. **协议规则已变更**——从"必须同步更新 `templates/README.md`"变更为"必须同步更新 `skills/README.md` 的模板交叉引用章节"。
3. **Agent 不得直接引用模板路径**——Agent 如需文档结构要求，需通过 Skill 调用获取或内联结构描述。
4. **`solution-designer` 不得重新激活**——如发现新的差异化需求，应在 `hld-designer` 上新增能力而非恢复 `solution-designer`。
5. **交叉引用限制**——消费者 Skill 只依赖 `.output/` 正式工件的内容契约，不通过路径交叉引用其他 Skill 的模板文件。
6. **新增 Skill 的模板要求**——新建 Skill 若携带模板，须在 `SKILL.md` 声明模板路径，并在 `skills/README.md` 的模板交叉引用章节登记关系。
7. **`docs/AGENT-SKILL-REFERENCE.md` 只记录已交付 Skill**，不记录历史占位 Skill。

---

## 12. 实施记录（2026-04-19）

### 12.1 已完成的整改动作

1. 删除仓库根 `templates/` 目录，并将仍有 canonical owner 的模板下沉到以下 Skill 私有目录：
   - `skills/requirement-clarifier/templates/CLARIFICATION-LOG-TEMPLATE.md`
   - `skills/requirement-extraction/templates/REQUIREMENTS-TEMPLATE.md`
   - `skills/state-router/templates/STATE-TEMPLATE.md`
   - `skills/hld-designer/templates/HLD-TEMPLATE.md`
   - `skills/story-manager/templates/STORY-TEMPLATE.md`
   - `skills/story-manager/templates/STORY-STATUS-TEMPLATE.md`
   - `skills/lld-designer/templates/STORY-LLD-TEMPLATE.md`
   - `skills/change-impact-analysis/templates/CR-TEMPLATE.md`
   - 既有私有模板继续保留：`issue-drafter`、`run-feedback-parser`、`workflow-renderer`、`context-manifest-builder`
2. 删除无 Skill owner 的独立模板文件，并将结构要求内联到相关 Agent：
   - `meta-po`：`REQUEST.md`、`INPUT-INDEX.md`、终验检查维度
   - `meta-se`：`ARCHITECTURE-DECISION.md`、`STORY-BACKLOG.md`、`DEVELOPMENT-PLAN.yaml`
   - `meta-qa`：`VALIDATION-ENV.yaml`、`INSTALL-MANIFEST.yaml`
   - `meta-dm`：删除历史模板路径引用，仅保留卡片结构说明
3. 更新所有相关 `skills/*/SKILL.md` 与 `.agents/skills/*/SKILL.md`：
   - producer Skill 改为引用 `skills/<skill>/templates/...`
   - consumer Skill（如 `issue-routing`）改为只依赖 `.output/` 正式工件内容契约
4. 将 `solution-designer` 收敛为 `status: deprecated` 的兼容入口，并把历史触发词合并到 `hld-designer`
5. 更新 `scripts/install.py`，删除共享模板安装逻辑，仅安装 Skill 私有模板
6. 更新治理与说明文件：
   - `README.md`
   - `AGENTS.md`
   - `rules/AGENTS.md`
   - `rules/CLAUDE.md`
   - `rules/copilot-instructions.md`
   - `.github/copilot-instructions.md`
   - `skills/README.md`
   - `docs/AGENT-SKILL-REFERENCE.md`

### 12.2 验证结果

已执行以下验证，并全部通过：

1. **目录验证**
   - 仓库根 `templates/` 已不存在
   - `.output/templates/` 约定未受影响
2. **引用验证**
   - 活跃文件中已无残留的根模板路径引用
   - 所有保留模板均位于 `skills/<skill-name>/templates/`
3. **安装验证**
   - `scripts/install.py` 已通过 `py_compile`
   - DryRun 与实际安装均已验证
   - 实际安装结果只包含 Skill 私有模板，不再生成根模板目录
4. **代表性运行态验证**
   - 已执行 `meta-se -> hld-designer` 代表性链路
   - Agent 能按当前编排合约调用 Skill，并生成符合当前 HLD 契约的结果内容
   - 受子 Agent 执行上下文限制，该次验证未直接落盘 `.output/doc/HLD.md`，但生成内容已按模板章节完成检查

### 12.3 结论

本方案定义的第二版整改目标已在仓库中完成落地，仓库当前实际状态已与“**无根 templates、Skill 持有模板、Agent 内联文档契约**”治理模型一致。
