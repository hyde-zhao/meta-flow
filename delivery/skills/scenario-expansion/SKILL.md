---
name: scenario-expansion
description: >-
  当已确认的 use cases / requirements 需要展开为正向、负向、边界、权限、
  失败恢复和 precheck 场景，并建立测试覆盖矩阵时使用。
  触发词包括：展开场景、生成场景、测试场景、场景扩展。
  适用场景：元工作流需求分析阶段，需求提取之后。
argument-hint: "USE-CASES.md 与 REQUIREMENTS.md 路径"
user-invokable: true
status: active
---

## 目标

从已确认的 `USE-CASES.md` / `REQUIREMENTS.md` 出发，生成工程可验证的 `SCENARIOS.yaml` 与 `TEST-MATRIX.md`。本 Skill 不做上游用户场景发现；真实用户场景仍由 `use-case-discovery` 负责。

## 适用场景

- 需求已结构化，需要展开测试覆盖面。
- 场景已确认，需要补齐正向、负向、边界、权限、失败恢复和 precheck 场景。
- 需要为产品规划、Feature 设计和后续验证建立需求到场景的回链。

## 前置条件

- [ ] `USE-CASES.md` 已生成，或 CP2 讨论明确给出 N/A 原因。
- [ ] `REQUIREMENTS.md` 已生成且条目完整。
- [ ] 每条需求有编号、优先级和验收条件。

## 必须读取的输入

- `docs/product/REQUIREMENTS.md`
- `docs/product/USE-CASES.md`
- 与需求相关的澄清结论（若存在）

## 知识来源

- `REQUIREMENTS.md` 的需求条目、优先级和验收条件
- `USE-CASES.md` 的 persona、成功指标、异常 / 边界和 Deferred Ideas
- `skills/scenario-expansion/templates/SCENARIOS-TEMPLATE.yaml`
- `skills/scenario-expansion/templates/TEST-MATRIX-TEMPLATE.md`
- 现有覆盖规则：`HIGH` 至少包含正向 + 负向；权限、安全、外部失败或 precheck 场景若不适用必须写明 N/A 原因

## 执行步骤

1. 按需求和 use case 逐条生成正向、负向、边界、权限、空数据、外部失败和前置检查场景。
2. 为每个场景填写前置条件、测试动作、期望结果、证据类型。
3. 为每个场景回链到 `REQ-*`、`UC-*` 和后续 `Story ID` 占位。
4. 生成 `TEST-MATRIX.md` 记录 Scenario、Requirement、Story、测试类型、自动化状态、手工验收状态与未覆盖原因。

## 输出文件 / 输出模板

| 文件 | 路径 | 说明 |
|---|---|---|
| 场景清单 | `docs/product/SCENARIOS.yaml` | `skills/scenario-expansion/templates/SCENARIOS-TEMPLATE.yaml` |
| 覆盖矩阵 | `docs/product/TEST-MATRIX.md` | `skills/scenario-expansion/templates/TEST-MATRIX-TEMPLATE.md` |

## 约束

- 依赖 `USE-CASES.md` / `REQUIREMENTS.md` 的内容契约，而不是模板文件存在性。
- 每个场景必须回链至少一条需求或 use case；无法回链的场景应转为 backlog / spike 候选。
- `HIGH` 优先级需求必须覆盖正向与负向。
- 不替代 `use-case-discovery` 做用户访谈或真实意图澄清。

## 验收标准

- [ ] 全部场景具备回链
- [ ] `HIGH` 级需求覆盖满足最低要求
- [ ] 覆盖矩阵统计正确

## 不适用边界

- 当前没有正式需求文档
- 当前任务是做上游用户场景发现，而不是生成工程验证场景
- 当前任务是做阶段设计，不是生成测试场景

## Gotchas

- 只生成正向场景会导致覆盖失真，尤其是安全与阻断类需求
- 边界场景和 precheck 场景常被忽略，但它们直接影响执行阶段稳定性
- `TEST-MATRIX.md` 若只列测试命令而不关联 Scenario / Story，后续质量评审无法判断覆盖缺口

