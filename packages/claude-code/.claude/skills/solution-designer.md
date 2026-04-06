---
name: solution-designer
description: >-
  当需要根据已确认需求判断产物复杂度、输出方案设计和架构决策时使用。
  触发词包括：方案设计、架构设计、复杂度判定、设计方案、simple/standard/complex 判断。
  适用场景：需求确认后的第一个设计步骤。
argument-hint: "可选：指定目标平台（如 copilot、claude-code）或约束条件"
user-invokable: true
status: active
---

## 目标

读取已确认的 `REQUIREMENTS.md`，结合目标平台约束，判断产物复杂度模式（simple / standard / complex），输出 `SOLUTION-DESIGN.md` 和 `ARCHITECTURE-DECISION.md`，并同步输出 `PLATFORM-INSTALL-SPEC.md`。

## 适用范围

- 适用阶段：`solution-design`
- 触发时机：`REQUIREMENTS.md` 状态为 `confirmed`，且 meta-po 唤醒 meta-se
- 输出消费方：meta-po（确认设计）、meta-dm（拆解 Story）、meta-dev（实现参考）

## 前置条件

- [ ] `.workflow-meta/REQUIREMENTS.md` 存在且 `status: confirmed`
- [ ] 已知目标平台（至少声明一个）

## 复杂度判定规则

| 判定维度 | simple | standard | complex |
|---------|--------|----------|---------|
| 目标数量 | 单一目标 | 1~2 个目标 | 3+ 个目标 |
| 角色数量 | 单一角色（1 个 Skill） | 1~2 个角色 | 3+ 个角色 |
| 状态流转 | 无 | 简单线性（< 5 步） | 多分支或并行 |
| 平台适配差异 | 无 | 轻微 | 显著 |
| Story 拆解必要性 | 否 | 可选 | 是 |

**输出判定结果**：在 `SOLUTION-DESIGN.md` 的 `complexity` 字段中填写 `simple` / `standard` / `complex`，并附上判定理由。

## 执行步骤

1. 读取 `REQUIREMENTS.md`，统计需求条目数量和角色边界
2. 按判定规则选定复杂度模式
3. 输出 `SOLUTION-DESIGN.md`：
   - 复杂度模式及理由
   - 产物形态（Skill 数量、Agent 数量）
   - 目标平台列表
   - 主要设计决策
4. 输出 `ARCHITECTURE-DECISION.md`：
   - Agent/Skill 组合方案
   - 各平台适配差异说明
   - 人工确认点（列出需用户确认的关键决策）
5. 输出 `PLATFORM-INSTALL-SPEC.md`：按目标平台填写安装目录、主入口文件、格式要求和验证方式

## 执行约束

- 不能修改 `REQUIREMENTS.md`
- 不能直接开始实现（不输出任何 Agent/Skill 文件）
- 不能绕过人工确认点直接进入 Story 拆解
- 设计确认点必须在 `ARCHITECTURE-DECISION.md` 中明确标注

## 输出文件

| 文件 | 路径 | 必填 |
|------|------|------|
| 方案设计 | `.workflow-meta/SOLUTION-DESIGN.md` | 是 |
| 架构决策 | `.workflow-meta/ARCHITECTURE-DECISION.md` | 是 |
| 平台安装规范 | `.workflow-meta/PLATFORM-INSTALL-SPEC.md` | 是 |

## 验收标准

- [ ] `SOLUTION-DESIGN.md` 包含 `complexity` 字段且值为 simple/standard/complex
- [ ] `ARCHITECTURE-DECISION.md` 包含至少 1 个人工确认点
- [ ] `PLATFORM-INSTALL-SPEC.md` 覆盖所有目标平台
- [ ] 未修改 `REQUIREMENTS.md`

## Gotchas

- 对于复杂度处于 standard/complex 边界的需求，优先选 standard，降低架构复杂度
- 目标平台未声明时，默认仅输出 GitHub Copilot 平台规范
- `PLATFORM-INSTALL-SPEC.md` 中必须标注各平台已知限制（如 Codex 不支持 Markdown Agent 格式）
