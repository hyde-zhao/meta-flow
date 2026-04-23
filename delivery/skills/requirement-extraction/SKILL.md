---
name: requirement-extraction
description: >-
  当用户提供自然语言需求，需要转化为结构化需求清单时使用。
  触发词包括：提取需求、整理需求、结构化需求、需求分析。
  适用场景：元工作流需求分析阶段。
argument-hint: "input_spec.yaml 路径、REQUEST.md 路径或自然语言需求描述"
user-invokable: true
status: active
---

## 目标

从用户自然语言需求、`REQUEST.md`、`process/USE-CASES.md` 或兼容输入（如 `input_spec.yaml`）中提取可编号、可追踪、可验证的结构化需求，按 `skills/requirement-extraction/templates/REQUIREMENTS-TEMPLATE.md` 生成 `REQUIREMENTS.md`。

## 适用场景

- requirement-clarification 阶段的结构化需求沉淀
- 用户已给出原始诉求，但尚未形成规范需求文档
- 上游 `use-case-discovery` 已输出 `USE-CASES.md`，需要直接消费正式场景工件
- 需要把自然语言、约束与目标转换为 `REQ-*` 列表

## 前置条件

- [ ] 已有用户原始需求描述、`REQUEST.md` 或 `input_spec.yaml`
- [ ] 若存在 `process/USE-CASES.md`，优先将其视为结构化事实来源
- [ ] 需求边界至少有可识别的目标、约束或平台信息

## 必须读取的输入

- 用户自然语言需求
- `process/REQUEST.md`（若存在）
- `process/USE-CASES.md`（若存在，且应作为显式兼容输入）
- `input_spec.yaml`（兼容旧输入方式，若存在）
- 已知的目标平台、约束、验收线索

## 兼容输入与来源映射

| 输入 | 角色 | 使用规则 |
|---|---|---|
| `process/USE-CASES.md` | 首选结构化真相源 | 若存在，必须直接消费其中的画像、成功指标、排除项、`UC-*` 场景字段以及治理字段（`target_artifact_type` / `governance_mode` / `review_policy`）；不得依赖 meta-pm 在会话中的二次转述 |
| `process/REQUEST.md` | 原始意图背景 | 用于补充初始目标、平台线索与未结构化背景，不替代 `USE-CASES.md` |
| 用户自然语言需求 | 补充输入 | 当 `USE-CASES.md` 不存在，或用户本轮补充了新约束 / 新目标时使用 |
| `input_spec.yaml` | 兼容旧入口 | 仅作为补充兼容来源，不高于 `USE-CASES.md` 的优先级 |

## 知识来源

- 用户输入、`USE-CASES.md` 与上游澄清结论：唯一事实来源
- `skills/requirement-extraction/templates/REQUIREMENTS-TEMPLATE.md`：输出结构基线
- `docs/SKILL-DEVELOPMENT-STANDARD.md`：`[待确认]` 与可追溯性要求

## 执行步骤

1. 先判定是否存在 `USE-CASES.md`；若存在，以其作为主输入提取画像、成功指标、排除项、`UC-*` 场景以及治理字段。
2. 提取需求目标、约束、验收线索与风险假设；`REQUEST.md` 和用户新增回复仅作为背景补充。
3. 若 `USE-CASES.md` 提供了 `target_artifact_type`、`governance_mode`、`review_policy`，在需求导言或来源上下文中保留这些治理线索，供后续规划和路由使用。
4. 将需求拆分为最小可验证单元，并分配 `REQ-NNN` 编号。
5. 为每条需求填写：类型、描述、优先级、验收条件、来源；若来源来自 `USE-CASES.md`，需优先回链到 `UC-*` / 相关场景字段。
6. 对无法从输入中确认的信息显式标记 `[待确认]`，不得自行脑补。
7. 生成或更新 `REQUIREMENTS.md`，并初始化变更记录表。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| 结构化需求 | `process/REQUIREMENTS.md` | `skills/requirement-extraction/templates/REQUIREMENTS-TEMPLATE.md` |

## 约束

- 输出必须遵循 `skills/requirement-extraction/templates/REQUIREMENTS-TEMPLATE.md`
- 若存在 `USE-CASES.md`，必须直接消费该正式工件，不得依赖 meta-pm 的口头重述
- 若 `USE-CASES.md` 含治理字段，必须显式消费，不得在需求提取阶段静默丢弃
- 每条需求必须有唯一 `REQ-NNN` 编号
- 验收条件必须具体可检验，优先使用 Given / When / Then
- 未确认信息必须写为 `[待确认]`，不得使用隐含默认值替代

## 验收标准

- [ ] `REQUIREMENTS.md` frontmatter 完整
- [ ] 每条需求含编号、优先级、验收条件与来源
- [ ] 若存在 `USE-CASES.md`，来源字段已回链到对应 `UC-*` 或其结构化章节
- [ ] 若存在治理字段，已在需求上下文中保留其来源与语义
- [ ] 无法确认的信息已显式标记 `[待确认]`
- [ ] 需求条目与变更记录表已初始化

## 不适用边界

- 当前任务是澄清问题列表而非输出正式需求
- 当前任务需要的是 HLD / LLD / 实现级设计
- 当前任务只要求发现 / 确认使用场景，此时应先完成 `use-case-discovery`
- 输入材料不足以形成任何可验证需求时，应先回到澄清阶段

## Gotchas

- 一个自然语言句子往往包含多条需求，不能机械地“一句一条”
- 约束信息也可能衍生出独立需求，例如安全边界、平台限制和交付方式
- 当 `USE-CASES.md` 已存在时，meta-pm 的会话转述只能作补充说明，不能替代正式场景工件
- `target_artifact_type` / `governance_mode` / `review_policy` 是上游治理线索，不是可随意忽略的“附加信息”
