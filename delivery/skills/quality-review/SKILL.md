---
name: quality-review
description: >-
  当实现 diff、测试 diff、验证执行证据或交付产物需要独立质量验证、测试报告、代码评审或安全初筛时使用。
  触发词包括：质量评审、测试报告、代码评审、REVIEW、TEST-REPORT。
  适用场景：实现完成后、发布确认前。
argument-hint: "diff、SCENARIOS.yaml、TEST-MATRIX.md、DESIGN.md、IMPLEMENTATION.md 或 Story ID"
user-invokable: true
status: active
---

## 目标

从独立验证视角输出 `TEST-REPORT.md`、`REVIEW.md` 和必要的 `FIXES.md` 输入，确保实现不是只“测试通过”，而是覆盖场景、Story、设计契约、实现证据、验证对象、风险和发布前缺口。

## 适用场景

- Story 或 Feature 已实现，需要验证场景覆盖和风险。
- 需要独立代码评审，避免实现代理自我确认。
- 需要把测试命令、测试结果、缺口和修复建议固化为可审计文件。

## 前置条件

- [ ] code diff 或产物文件已存在。
- [ ] `docs/product/SCENARIOS.yaml` 和 `docs/product/TEST-MATRIX.md` 可读取，或缺失原因已记录。
- [ ] 相关 `DESIGN.md`、Story LLD 或任务清单可读取。
- [ ] 相关 Story 的实现执行证据可读取，或 CP6 已写明低风险 N/A 理由。
- [ ] `verification-execution` 产出的验证对象清单、验证追踪矩阵、设计契约验证清单、分层验证计划和阶段决策可读取，或低风险 N/A 理由已记录。

## 必须读取的输入

- git diff 或实现文件清单
- `docs/product/SCENARIOS.yaml`
- `docs/product/TEST-MATRIX.md`
- `docs/features/<feature>/DESIGN.md` 或 `process/stories/STORY-*-LLD.md`
- `process/stories/STORY-*-IMPLEMENTATION.md`、`docs/features/<feature>/IMPLEMENTATION.md`，或 Story 卡片 `implementation_context` / DEV-LOG 中的实现摘要
- `docs/quality/VERIFICATION-REPORT.md` 或 Feature scoped 等价文件（若存在）
- 测试命令输出和失败日志（若存在）

## 知识来源

- `skills/quality-review/templates/TEST-REPORT-TEMPLATE.md`
- `skills/quality-review/templates/REVIEW-TEMPLATE.md`
- `skills/quality-review/templates/FIXES-TEMPLATE.md`
- `review-artifact-protocol` 的 findings / summary 结构

## 执行步骤

1. 校验测试矩阵是否覆盖场景、Story、测试类型、自动化状态和未覆盖原因。
2. 读取验证执行证据，核对验证对象清单、验证追踪矩阵、设计契约验证清单、分层验证计划、问题清单、剩余风险和阶段决策是否完整。
3. 读取实现执行证据，核对实现对象清单、设计契约映射、测试 / Fixture 计划、最小实现切片和平台差异检查是否完整；缺失项必须作为评审风险记录。
4. 运行或读取测试命令，记录命令、环境、结果、失败原因和证据路径。
5. 按高 / 中 / 低风险顺序审查 diff，优先找缺陷、回归、安全、架构偏离、契约未闭环和测试缺口。
6. 输出 `REVIEW.md`，阻断问题必须有文件路径、影响、复现 / 证据和建议修复方向。
7. 若存在需要实现代理回修的问题，输出 `FIXES.md` 草案或修复输入。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| 测试报告 | `docs/quality/TEST-REPORT.md` 或 `docs/features/<feature>/TEST-REPORT.md` | `skills/quality-review/templates/TEST-REPORT-TEMPLATE.md` |
| 评审报告 | `docs/quality/REVIEW.md` 或 `docs/features/<feature>/REVIEW.md` | `skills/quality-review/templates/REVIEW-TEMPLATE.md` |
| 修复输入 | `docs/quality/FIXES.md` 或 `docs/features/<feature>/FIXES.md` | `skills/quality-review/templates/FIXES-TEMPLATE.md` |

## 约束

- 不修改验收目标；发现目标错误时回到规划 / 设计阶段。
- 不直接大规模重写实现；评审输出问题和修复方向，回修由实现代理处理。
- `TEST-REPORT.md` 必须说明覆盖缺口，不能只列“全部通过”。
- `TEST-REPORT.md` 必须包含验证范围、验证对象清单、追踪矩阵、设计契约验证、分层验证计划、自动化 / fixture / dry-run 证据、问题与剩余风险和阶段决策；低风险 N/A 必须写明原因。
- `REVIEW.md` 必须 findings 优先，按严重度排序。
- `REVIEW.md` 必须包含人工 / 语义质量审查，覆盖需求一致性、场景覆盖、Prompt 边界、文档可用性、错误信息和 happy path 偏差。
- 复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / 护栏 / 平台适配 / 发布相关 Story 缺少完整 `IMPLEMENTATION.md` 时，不得给出“实现证据完整”的结论；低风险 N/A 必须引用 CP6 或 Story 卡片中的理由。

## 验收标准

- [ ] 测试结果能回链到场景 ID、Story ID 或风险 ID。
- [ ] 验证对象清单、追踪矩阵、设计契约验证和分层验证计划能支撑 CP7 阶段决策。
- [ ] 实现对象、设计契约、测试 / Fixture、实现切片和平台差异能回链到 Story 或 Feature 设计证据。
- [ ] 每个失败或缺口有下一动作和责任方。
- [ ] 评审 findings 包含位置、影响和建议。
- [ ] 发布前阻断项明确标记为 BLOCKING。

## 不适用边界

- 还未完成实现或没有可审查 diff。
- 当前任务是场景发现或产品规划。
- 用户只要求解释代码，不要求质量判断。

## Gotchas

- 评审代理不应把“测试通过”当作无风险结论；覆盖矩阵缺失本身就是风险。
- 安全、权限和迁移问题即使没有自动测试失败，也可能阻断发布。
- 自我评审容易漏掉实现者假设，必要时使用新上下文或独立 reviewer lane。
