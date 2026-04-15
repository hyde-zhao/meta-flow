---
name: hld-designer
description: >-
  当需要将已确认需求转化为可评审、可决策、可交接的 High-Level Design（HLD）时使用。
  输出问题定义、候选架构方案对比、推荐方案、架构图、模块职责、技术选型、关键流程、
  非功能设计、风险、ADR 候选点和分阶段落地建议。触发词包括：HLD、高层设计、架构评审、架构方案。
argument-hint: "可选：指定目标平台、技术栈约束或既有系统边界"
user-invokable: true
status: active
---

## 目标

基于已确认的 `REQUIREMENTS.md`、`USE-CASES.md` 和补充约束，输出一份**可直接进入人工评审**的 `.output/doc/HLD.md`。文档必须能作为后续 Story 拆解和 LLD 设计的上游输入，而不是停留在概念讨论层。

## 核心原则

1. **结论先行**：先说明问题、目标和推荐方案，再展开细节
2. **边界清晰**：明确事实、假设、约束、非目标和未决问题
3. **方案可比较**：至少给出 2 个候选方案，并做显式权衡
4. **评审可用**：内容必须适合产品、技术负责人和开发团队共同评审
5. **不过早下沉**：不写类、函数、字段级实现细节；仅在影响架构决策时给出必要精度

## 前置条件

- [ ] `.output/doc/REQUIREMENTS.md` 存在且 `confirmed=true`
- [ ] `.output/doc/USE-CASES.md` 存在且 `status=confirmed`
- [ ] 已知目标平台、交付范围或关键约束至少有一项明确

## 必须读取的输入

- `.output/doc/REQUIREMENTS.md`
- `.output/doc/USE-CASES.md`
- `.output/doc/REQUEST.md`
- `.output/doc/INPUT-INDEX.md`（若存在）
- 与当前需求直接相关的补充约束或参考资料

## 执行步骤

### 步骤 1：问题定义

提炼并写入以下信息：

- 当前问题与为什么现在解决
- 业务价值与技术价值
- 目标与成功标准
- 硬约束、非目标、关键假设
- 缺失信息（标注 `BLOCKING` / `NON-BLOCKING`）

若存在 `BLOCKING` 缺失信息，停止在问题定义，不继续输出方案正文。

### 步骤 2：候选架构方案

至少产出 2 个候选方案，每个方案必须包含：

- 核心思路
- 适用前提
- 关键架构风格
- 核心模块与边界
- 外部依赖与集成关系
- 优点、缺点、成本、复杂度、扩展性、风险

### 步骤 3：推荐方案

在比较后明确推荐 1 个方案，并说明：

- 推荐理由（至少 3 条）
- 不推荐其他方案的主要原因
- 适用边界与未来演进路径

### 步骤 4：推荐方案正文

`HLD.md` 必须严格包含以下章节：

1. 问题定义
2. 目标、约束与非目标
3. 候选架构方案对比
4. 推荐方案总览
5. 系统架构图（Mermaid，覆盖 User / Application / Service / Data / Infrastructure）
6. 高层模块与职责划分
7. 技术选型与理由
8. 关键流程（步骤或 Mermaid sequence）
9. 非功能需求设计
10. 主要风险与应对
11. 需要沉淀为 ADR 的决策点
12. 分阶段落地建议
13. 工作量粗估（T-Shirt Size）
14. 待确认问题

### 步骤 5：评审门控

完成 `.output/doc/HLD.md` 后：

- 在 Frontmatter 中设置 `status: ready-for-review`
- 在 Frontmatter 中设置 `confirmed: false`
- 明确写出“该文档需由 meta-po 发起人工确认”
- **立即停止**，不得继续拆解 Story 或补写实现级设计

## 输出文件

| 文件 | 路径 | 说明 |
|------|------|------|
| HLD 文档 | `.output/doc/HLD.md` | 供 meta-po 发起人工评审的高层设计文档 |

## 验收标准

- [ ] `HLD.md` 覆盖 14 个规定章节
- [ ] 至少给出 2 个候选方案并完成显式对比
- [ ] 推荐方案有清晰推荐理由与局限性说明
- [ ] 包含至少 1 张 5 层架构 Mermaid 图
- [ ] 包含非功能设计、风险表、ADR 候选点与分阶段建议
- [ ] 明确区分事实 / 假设 / 建议
- [ ] `confirmed=false` 时不输出下游 Story 计划文件

## 不适用边界

- `REQUIREMENTS.md` 尚未确认
- 当前任务只要求某个 Story 的实现细节或代码级设计
- 已进入 Story 实施阶段，需要的是 LLD 而不是 HLD
