---
name: solution-designer
description: >-
  当需要根据已确认需求设计可执行方案时使用。先定义问题边界（目标/约束/非目标/假设），
  再输出≥2个候选方案进行六维度强制比较，推荐方案后交由人工选择确认。
  触发词包括：方案设计、架构设计、复杂度判定、设计方案、simple/standard/complex 判断。
  适用场景：需求确认后的第一个设计步骤。
argument-hint: "可选：指定目标平台（如 copilot、claude-code）或约束条件"
user-invokable: true
status: active
---

## 目标

读取已确认的 `REQUIREMENTS.md`，**先提炼问题边界**（目标、约束、非目标、成功标准、缺失前提），再设计 ≥2 个候选方案进行六维度比较，推荐方案后**交由人工选择确认**，确认后输出 `SOLUTION-DESIGN.md`、`ARCHITECTURE-DECISION.md` 和 `PLATFORM-INSTALL-SPEC.md`。

## 核心原则

1. **边界先行**：先定义问题边界，再给方案。信息不足时列出缺失清单，不假设
2. **多方案比较**：强制 ≥2 方案 + 六维度对比，避免单一方案偏见
3. **人工确认门控**：方案选择必须人工确认，未确认不输出设计文件
4. **可执行导向**：输出可直接用于评审和 Story 拆解的 Markdown 文档，不做概念性建议
5. **风险显性化**：每个方案必须列出风险、失败点和应对策略

## 适用范围

- 适用阶段：`solution-design`
- 触发时机：`REQUIREMENTS.md` 状态为 `confirmed`，且 meta-po 唤醒 meta-se
- 输出消费方：meta-po（发起人工确认）、meta-se 步骤二（拆解 Story）、meta-dev（实现参考）

## 前置条件

- [ ] `.workflow-meta/REQUIREMENTS.md` 存在且 `status: confirmed`
- [ ] `.workflow-meta/USE-CASES.md` 存在且 `status: confirmed`
- [ ] 已知目标平台（至少声明一个）

## 复杂度判定规则

| 判定维度 | simple | standard | complex |
|---------|--------|----------|---------|
| 目标数量 | 单一目标 | 1~2 个目标 | 3+ 个目标 |
| 角色数量 | 单一角色（1 个 Skill） | 1~2 个角色 | 3+ 个角色 |
| 状态流转 | 无 | 简单线性（< 5 步） | 多分支或并行 |
| 平台适配差异 | 无 | 轻微 | 显著 |
| Story 拆解必要性 | 否 | 可选 | 是 |

## 执行步骤

### Phase 1：问题定义（边界先行）

1. 读取 `REQUIREMENTS.md` 和 `USE-CASES.md`
2. 提炼并输出以下字段到 `SOLUTION-OPTIONS.md` 的"问题定义"章节：
   - **问题陈述**：一段话描述核心问题
   - **目标**：3~5 条量化可度量目标
   - **已知约束**：技术/平台/合规/业务约束
   - **非目标**：明确不做的内容（不可为空）
   - **关键假设**：每条标注验证方式
   - **成功标准**：如何判断方案成功
   - **缺失信息**：标注 BLOCKING / NICE-TO-HAVE 级别
3. 若存在 **BLOCKING 级缺失信息**，暂停方案设计，交由 meta-po 澄清

### Phase 2：候选方案设计

4. 按判定规则选定复杂度模式
5. 输出 ≥2 个候选方案，每个方案包含：
   - 设计理念 + 组件清单 + 组件关系
   - 5 层 Mermaid 架构图
   - 技术选型理由表
6. 输出六维度强制对比表：复杂度、成本、扩展性、风险、实施周期、维护性
7. 明确推荐一个方案：推荐理由（≥3 条）+ 局限性 + 演进路径

### Phase 3：风险与待确认

8. 输出风险与应对表：风险描述、失败点、概率、影响、监控指标、应对策略
9. 输出待确认问题列表 + 下一步行动建议

### 🔒 Phase 4：人工确认门控

10. **暂停**，设置 `SOLUTION-OPTIONS.md` 的 `status: user_selecting`
11. 由 meta-po 通过 `ask_user` 发起方案选择确认
12. 用户选定方案后，继续执行 Phase 5

### Phase 5：选定方案详细设计

13. 输出 `SOLUTION-DESIGN.md`：复杂度模式 + 选定方案详细架构 + 分阶段实施计划
14. 输出 `ARCHITECTURE-DECISION.md`：Agent/Skill 组合方案 + 平台差异 + 设计确认点
15. 输出/更新 `PLATFORM-INSTALL-SPEC.md`：按目标平台填写安装目录、入口、格式、验证方式

## 执行约束

- 不能修改 `REQUIREMENTS.md` 或 `USE-CASES.md`
- 不能直接开始实现（不输出任何 Agent/Skill 文件）
- 🔒 **不能绕过人工确认直接输出 SOLUTION-DESIGN.md** — 必须先由用户选定方案
- 设计确认点必须在 `ARCHITECTURE-DECISION.md` 中明确标注
- 非目标章节不可为空
- 关键假设必须标注验证方式

## 输出文件

| 文件 | 路径 | 输出时机 | 必填 |
|------|------|---------|------|
| 方案备选 | `.workflow-meta/SOLUTION-OPTIONS.md` | Phase 1-3 完成后 | 是 |
| 方案设计 | `.workflow-meta/SOLUTION-DESIGN.md` | Phase 5（人工确认后） | 是 |
| 架构决策 | `.workflow-meta/ARCHITECTURE-DECISION.md` | Phase 5（人工确认后） | 是 |
| 平台安装规范 | `.workflow-meta/PLATFORM-INSTALL-SPEC.md` | Phase 5（人工确认后） | 是 |

## 验收标准

- [ ] `SOLUTION-OPTIONS.md` 包含完整的问题定义章节（7 个字段均非空）
- [ ] 若存在 BLOCKING 缺失信息，已暂停并交由 meta-po 澄清
- [ ] `SOLUTION-OPTIONS.md` 包含 ≥2 个候选方案，每个有 5 层 Mermaid 图
- [ ] 六维度对比表完整（复杂度/成本/扩展性/风险/实施周期/维护性）
- [ ] 包含明确推荐方案 + ≥3 条推荐理由 + 局限性 + 演进路径
- [ ] 包含风险与应对表 + 待确认问题列表
- [ ] 🔒 `SOLUTION-DESIGN.md` 仅在人工确认后输出
- [ ] `ARCHITECTURE-DECISION.md` 包含至少 1 个设计确认点
- [ ] `PLATFORM-INSTALL-SPEC.md` 覆盖所有目标平台
- [ ] 未修改 `REQUIREMENTS.md` 或 `USE-CASES.md`

## Gotchas

- 对于复杂度处于 standard/complex 边界的需求，优先选 standard，降低架构复杂度
- 目标平台未声明时，默认仅输出 GitHub Copilot 平台规范
- `PLATFORM-INSTALL-SPEC.md` 中必须标注各平台已知限制（如 Codex 不支持 Markdown Agent 格式）
- 问题定义阶段发现的缺失信息不可自行假设填充，必须走 meta-po 澄清流程
- 推荐方案不等于确认方案 — 用户有权选择任何候选方案
