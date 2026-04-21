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

从用户自然语言需求、`REQUEST.md` 或兼容输入（如 `input_spec.yaml`）中提取可编号、可追踪、可验证的结构化需求，按 `skills/requirement-extraction/templates/REQUIREMENTS-TEMPLATE.md` 生成 `REQUIREMENTS.md`。

## 适用场景

- requirement-clarification 阶段的结构化需求沉淀
- 用户已给出原始诉求，但尚未形成规范需求文档
- 需要把自然语言、约束与目标转换为 `REQ-*` 列表

## 前置条件

- [ ] 已有用户原始需求描述、`REQUEST.md` 或 `input_spec.yaml`
- [ ] 需求边界至少有可识别的目标、约束或平台信息

## 必须读取的输入

- 用户自然语言需求
- `.meta-workflow/process/REQUEST.md`（若存在）
- `input_spec.yaml`（兼容旧输入方式，若存在）
- 已知的目标平台、约束、验收线索

## 知识来源

- 用户输入与上游澄清结论：唯一事实来源
- `skills/requirement-extraction/templates/REQUIREMENTS-TEMPLATE.md`：输出结构基线
- `docs/SKILL-DEVELOPMENT-STANDARD.md`：`[待确认]` 与可追溯性要求

## 执行步骤

1. 提取需求目标、约束、验收线索与风险假设。
2. 将需求拆分为最小可验证单元，并分配 `REQ-NNN` 编号。
3. 为每条需求填写：类型、描述、优先级、验收条件、来源。
4. 对无法从输入中确认的信息显式标记 `[待确认]`，不得自行脑补。
5. 生成或更新 `REQUIREMENTS.md`，并初始化变更记录表。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| 结构化需求 | `.meta-workflow/process/REQUIREMENTS.md` | `skills/requirement-extraction/templates/REQUIREMENTS-TEMPLATE.md` |

## 约束

- 输出必须遵循 `skills/requirement-extraction/templates/REQUIREMENTS-TEMPLATE.md`
- 每条需求必须有唯一 `REQ-NNN` 编号
- 验收条件必须具体可检验，优先使用 Given / When / Then
- 未确认信息必须写为 `[待确认]`，不得使用隐含默认值替代

## 验收标准

- [ ] `REQUIREMENTS.md` frontmatter 完整
- [ ] 每条需求含编号、优先级、验收条件与来源
- [ ] 无法确认的信息已显式标记 `[待确认]`
- [ ] 需求条目与变更记录表已初始化

## 不适用边界

- 当前任务是澄清问题列表而非输出正式需求
- 当前任务需要的是 HLD / LLD / 实现级设计
- 输入材料不足以形成任何可验证需求时，应先回到澄清阶段

## Gotchas

- 一个自然语言句子往往包含多条需求，不能机械地“一句一条”
- 约束信息也可能衍生出独立需求，例如安全边界、平台限制和交付方式

