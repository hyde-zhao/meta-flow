---
name: context-handoff
description: >-
  当阶段切换时需要为下一个 Agent 装配最小必要上下文时使用。
  触发词包括：上下文交接、装配上下文、阶段切换、交接给。
  适用场景：Orchestrator 将控制权移交给下一个功能 Agent。
argument-hint: "目标 Agent 名称"
user-invokable: false
status: active
---

## 目标

根据目标 Agent 的职责，从 `.output/` 工作区中筛选最小必要上下文，并明确哪些内容不应加载，确保交接简洁且不越权。

## 适用场景

- `meta-po` 向 `meta-pm` / `meta-se` / `meta-dev` / `meta-qa` / `meta-doc` 交接
- 阶段切换或 Story 执行中角色切换

## 前置条件

- [ ] 目标 Agent 已明确
- [ ] `.output/` 下相关输入文档已生成

## 必须读取的输入

- `.output/doc/STATE.md`
- 目标 Agent 对应阶段的正式对象
- 活跃 `CR-*` / 当前 Story 卡片（若存在）

## 知识来源

- `AGENTS.md`：角色职责与阶段定义
- `.output/doc/STATE.md`：当前阶段、当前 Wave、活跃变更
- 正式对象的文件路径与 frontmatter：决定是否需要加载

## 执行步骤

1. 识别目标 Agent 的职责边界。
2. 选择该 Agent 完成当前任务所需的最小文件集合。
3. 显式列出不应加载的历史草稿、中间推理和无关产物。
4. 若存在活跃变更单或当前 Story，补入对应上下文。

## 输出文件 / 输出模板

输出为上下文加载清单；不依赖模板文件。

## 约束

- 只加载正式对象，不加载其他 Agent 的历史推理过程
- 活跃 `CR-*`、当前 Story 与当前阶段状态必须优先纳入
- 只使用当前 `.output/` 工作区路径

## 验收标准

- [ ] 输出清单能支持目标 Agent 完成当前任务
- [ ] 不包含无关阶段草稿或历史失败轮次
- [ ] 活跃变更与当前 Story 上下文已纳入

## 不适用边界

- 只是查询文件内容，不涉及 Agent 交接
- 目标 Agent 未明确

## Gotchas

- Story 执行阶段通常同时存在 Wave 级和 Story 级上下文，不能只给其中一层
- 文档太多时应优先给“当前正式版本”，不要把历史稿与现行稿混装
