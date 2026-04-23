---
story_id: "LLD-01"
story_title: "lld-designer 六阶段管道与输入输出契约"
status: "confirmed"
tier: "S"
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T11:47:36+08:00"
created_at: "2026-04-23T11:47:36+08:00"
updated_at: "2026-04-23T11:47:36+08:00"
source_story: "process/stories/STORY-LLD-01.md"
source_hld:
  - "process/HLD-lld-writing-method.md"
architecture_decision: "process/ARCHITECTURE-DECISION.md"
platform_spec: "process/PLATFORM-INSTALL-SPEC.md"
---

# LLD - LLD-01 lld-designer 六阶段管道与输入输出契约

## 1. Goal

把 Story LLD 写作方法固化为 `lld-designer` Skill 的正式入口合同，使其在 Story 批准后能产出统一 14 章节 LLD，并在人工确认前停止。

## 2. Requirements

### Functional

- F1：Skill 必须定义 Ready Check、Scope Extraction、Contract Mapping、Drafting、Review Prep、Checkpoint Handoff 六阶段。
- F2：Skill 必须明确输入对象：Story、HLD、ADR、依赖 Story、平台规范、CR。
- F3：Skill 必须明确输出对象：`STORY-{id}-LLD.md`、OPEN/Spike、确认区。
- F4：Skill 必须定义 blocked / 回退 / Spike / 人工确认的失败路径。

### Non-Functional

- NF1：始终保持 14 个可见章节。
- NF2：不得把实现日志混进 LLD 说明。
- NF3：与 `meta-dev` / `meta-qa` / rules 的契约可追溯。

## 3. 模块拆分与职责

| 模块 | 职责 | 输入 | 输出 |
|---|---|---|---|
| Ready Check | 校验 Story 状态和上游确认位 | Story/HLD/ADR/平台规范 | 是否允许起草 |
| Contract Mapper | 把 Story 约束映射到 14 章节 | Story、HLD、ADR | 章节输入/输出分配 |
| LLD Drafter | 生成 14 章节正文 | 章节映射结果 | `STORY-{id}-LLD.md` |
| Failure Handler | 处理 OPEN/Spike/blocked | 缺失输入、冲突 | 升级与停止动作 |
| Handoff Builder | 整理确认区和等待状态 | LLD 草稿 | `ready-for-lld-review` 停点 |

## 4. 代码结构与文件影响范围

| 动作 | 文件 | 说明 |
|---|---|---|
| 修改 | `delivery/skills/lld-designer/SKILL.md` | 固化 6 阶段流程、输入输出契约、失败路径 |

## 5. 数据模型与持久化设计

本 Story 不新增仓库持久化模型；需要在 Skill 契约中显式化以下逻辑模型：

| 对象 | 字段 | 说明 |
|---|---|---|
| LLD Context | `story_id`, `tier`, `inputs`, `constraints` | 起草前上下文集合 |
| Open Item | `id`, `topic`, `owner`, `next_action` | 未决问题结构 |
| Checkpoint State | `confirmed`, `confirmed_by`, `confirmed_at` | 人工确认区状态 |

## 6. API / Interface 设计

| 接口 | 输入 | 输出 | 错误/异常 |
|---|---|---|---|
| meta-dev -> lld-designer | 已批准 Story、已确认 HLD/ADR | 结构化 LLD 草稿 | Story 未批准 / HLD 未确认 |
| lld-designer -> meta-po | 待确认 LLD | checkpoint ④ 触发条件 | LLD 章节不完整 |
| lld-designer -> meta-qa | 测试设计与异常路径 | 可消费的验证入口 | 接口和测试未配对 |

## 7. 核心处理流程

1. Ready Check：检查 Story、HLD、ADR、平台规范、依赖输入是否满足。
2. Scope Extraction：提取目标文件、验收标准、约束与平台目标。
3. Contract Mapping：将约束映射到 14 个章节。
4. Drafting：按 14 章节生成 LLD 正文。
5. Review Prep：生成 OPEN/Spike、DoD 和确认区。
6. Checkpoint Handoff：产出文档并停止在 `ready-for-lld-review`。

### 异常流程

- 若 Story 非 approved，则 blocked，不得起草。
- 若关键输入缺失，则 blocked，并写明缺失对象。
- 若存在技术未决且影响实现边界，则输出 OPEN 或 Spike，不得伪确定。

## 8. 技术设计细节

- 六阶段使用编号步骤和表格表达，避免正文散落。
- 章节级输入/输出契约与 HLD §3.4 保持一一对应。
- `ARCHITECTURE-DECISION.md` 采用条件必需语义，命中关键取舍时必须读取。

## 9. 安全与性能设计

- Skill 只生成设计文档，不执行代码或脚本。
- 对缺失输入采取显式阻断，不做默认成功。
- 生成内容需避免泄漏与 Story 无关的对象范围。

## 10. 测试设计

| 测试点 | 输入场景 | 期望结果 |
|---|---|---|
| T-01 | Story 已 approved，输入完整 | 成功生成 14 章节 LLD |
| T-02 | Story 缺少 HLD 或 ADR | blocked，明确缺失项 |
| T-03 | Story 有技术未决 | 输出 OPEN/Spike，而非继续实现 |
| T-04 | 接口章节已写 | 测试设计章节可找到对应测试入口 |

## 11. 实施步骤

| TASK-ID | 动作 | 目标文件 | 详细步骤 | 验证对应 |
|---|---|---|---|---|
| T1 | 修改 | `delivery/skills/lld-designer/SKILL.md` | 加入六阶段主流程 | T-01 |
| T2 | 修改 | `delivery/skills/lld-designer/SKILL.md` | 固化输入/输出契约与章节映射 | T-01,T-04 |
| T3 | 修改 | `delivery/skills/lld-designer/SKILL.md` | 增加失败路径与回退决策 | T-02,T-03 |
| T4 | 修改 | `delivery/skills/lld-designer/SKILL.md` | 增加 Gotchas、Tier 语义与图示规则引用 | T-01 |

## 12. 风险、难点与预研建议

| 风险 | 影响 | 应对 |
|---|---|---|
| 六阶段与现有简版说明不一致 | 读者混淆 | 以 Skill 为唯一正式入口 |
| 条件必需 ADR 边界不清 | Ready Check 分歧 | 先在 Skill 中显式列出触发条件 |
| OPEN/Spike 规范不清 | 设计漂移 | 在模板和 rules 中后续同步 |

## 13. 回滚与发布策略

- 若六阶段改造影响现有消费方，可先保留旧结构说明并回滚新增子步骤。
- 改造为单文件文档更新，无额外安装脚本变更。
- 若与模板章节不一致，以模板契约回调 Skill 内容。

## 14. Definition of Done + 确认区

### Definition of Done

- [x] `SKILL.md` 写明六阶段主流程
- [x] 输入对象覆盖 Story/HLD/ADR/依赖/平台/CR
- [x] 输出对象覆盖 LLD、OPEN/Spike、确认区
- [x] 失败路径覆盖 blocked / 回退 / Spike / 人工确认

### 确认区

- `confirmed`: true
- 待确认事项：
  1. ADR 条件必需是否在 Ready Check 中单列示例条件
  2. Checkpoint Handoff 是否需要明确引用 `DEV-LOG.md`
