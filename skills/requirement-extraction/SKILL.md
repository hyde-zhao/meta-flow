---
name: requirement-extraction
description: >-
  当用户提供自然语言需求，需要转化为结构化需求清单时使用。
  触发词包括：提取需求、整理需求、结构化需求、需求分析。
  适用场景：元工作流需求分析阶段。
argument-hint: "input_spec.yaml 路径或自然语言需求描述"
user-invokable: true
status: draft
---

## 目标

从 `input_spec.yaml` 和用户自然语言描述中，提取可编号、可追踪、可验证的结构化需求清单，输出为 `REQUIREMENTS.md`。

## 适用范围

- 适用阶段：需求分析阶段（requirement）
- 输入来源：`input_spec.yaml` + 用户补充描述
- 输出：`REQUIREMENTS.md`

## 前置条件

- [ ] `input_spec.yaml` 已录入且字段完整
- [ ] 用户已确认测试目标和约束条件

## 执行约束

- 每条需求必须有唯一 `REQ-NNN` 编号，三位数字递增
- 每条需求必须包含：描述、优先级、验证标准、来源追踪
- 验证标准必须具体可测量，禁止使用"正常工作"、"功能可用"等模糊表述
- 从 `test_objectives` 提取核心需求，从 `constraints` 提取限制类需求，从 `security_boundaries` 提取安全需求
- 同一个 `test_objective` 可以拆分为多条 REQ（如正向验证和负向验证）
- 输出格式严格遵循 `.fw-meta/templates/REQUIREMENTS.md`

## 提取优先级判定

| input_spec 字段 | 映射 REQ 优先级 | 说明 |
|----------------|----------------|------|
| test_objectives.priority = HIGH | REQ 优先级 = HIGH | 直接映射 |
| test_objectives.priority = MEDIUM | REQ 优先级 = MEDIUM | 直接映射 |
| constraints.type = security | REQ 优先级 ≥ HIGH | 安全约束强制高优先级 |
| security_boundaries 中任何 false/true | REQ 优先级 = HIGH | 安全边界约束 |

## Gotchas

- 用户描述中经常隐含多条需求（如"验证 ACL 策略的放行和阻断"实际包含正向放行验证和负向阻断验证两条 REQ），需要主动拆分
- `constraints` 中的约束条件不仅是限制，还可能衍生出专门的验证需求（如"不能影响生产网"应衍生 REQ：验证测试操作不会影响生产网段流量）

## 验收标准

- 输出的 `REQUIREMENTS.md` frontmatter 完整
- 每条 REQ 有唯一编号、优先级、验证标准
- 没有模糊的验证标准
- 来源追踪字段指向 input_spec 中的具体条目
- 需求汇总表与正文条目一致
