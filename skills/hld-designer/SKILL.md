---
name: hld-designer
description: >-
  当需要将已确认需求转化为可评审、可决策、可交接的 High-Level Design（HLD）时使用。
  输出问题定义、候选架构方案对比、推荐方案、架构图、模块职责、技术选型、关键流程、
  非功能设计、风险、ADR 候选点和分阶段落地建议。兼容历史触发词：方案设计、架构设计、
  复杂度判定、设计方案、simple/standard/complex 判断。触发词包括：HLD、高层设计、架构评审、架构方案。
argument-hint: "可选：指定目标平台、技术栈约束或既有系统边界"
user-invokable: true
status: active
---

## 目标

基于已确认需求与场景，先输出 `.meta-workflow/process/HLD.md`，再生成供人工确认的 `.meta-workflow/checkpoints/CHECKPOINT-HLD.md`。

## 适用场景

- 需求已确认，需要进入正式高层设计
- 需要形成可评审、可交接、可作为 Story 拆解输入的设计文档

## 前置条件

- [ ] `.meta-workflow/process/REQUIREMENTS.md` 已确认
- [ ] `.meta-workflow/process/USE-CASES.md` 已确认

## 必须读取的输入

- `.meta-workflow/process/REQUIREMENTS.md`
- `.meta-workflow/process/USE-CASES.md`
- `.meta-workflow/process/REQUEST.md`
- 补充约束与参考资料（若存在）

## 知识来源

- 已确认的需求、场景和约束
- `skills/hld-designer/templates/HLD-TEMPLATE.md`
- `AGENTS.md` 中的阶段门控与下游设计需求

## 执行步骤

1. 输出问题定义、目标、约束与非目标。
2. 给出至少 2 个候选方案并完成显式比较。
3. 明确推荐方案、关键架构图、模块职责、技术选型和风险。
4. 生成 `.meta-workflow/process/HLD.md`，并同步整理 `.meta-workflow/checkpoints/CHECKPOINT-HLD.md` 供人工确认。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| HLD 过程稿 | `.meta-workflow/process/HLD.md` | `skills/hld-designer/templates/HLD-TEMPLATE.md` |
| HLD 检查点稿 | `.meta-workflow/checkpoints/CHECKPOINT-HLD.md` | `skills/hld-designer/templates/HLD-TEMPLATE.md` |

## 约束

- 输出必须遵循 `skills/hld-designer/templates/HLD-TEMPLATE.md`
- 未确认前不得继续 Story 拆解
- 不下沉到类、函数或字段级实现设计

## 验收标准

- [ ] HLD 覆盖规定章节
- [ ] 至少 2 个候选方案已完成比较
- [ ] 推荐方案、风险和待确认问题明确

## 不适用边界

- 当前需要的是 LLD 或代码实现设计
- 需求尚未确认

## Gotchas

- 候选方案不能只是一个方案换不同措辞，必须有真实权衡差异
- 推荐方案若缺少适用边界说明，后续 Story 拆解很容易失真

