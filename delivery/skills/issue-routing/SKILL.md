---
name: issue-routing
description: >-
  当需要对 ISSUE 问题工单进行分类、定级和路由到正确 Agent 时使用。
  触发词包括：路由问题、分配问题、ISSUE 路由、问题分流。
  适用场景：执行反馈产生 ISSUE 后的分流决策。
argument-hint: "ISSUE 工单 ID 或问题描述"
user-invokable: true
status: active
---


## vNext 过程引用契约

- `process/...` 是过程仓逻辑引用，不是发布仓中的相对物理路径。
- 首次文件系统 I/O 前必须调用 `meta-flow project resolve-ref --project-root <release-root> --logical-ref <process/...> --format json`。
- 只可瞬时使用成功 JSON 中的 `resolved_path`；不得把绝对路径写入治理文件、Prompt 产物或 Git。
- 命令以退出码 2 返回 BLOCKED 时必须停止；不得自行拼 sibling、去掉 `process/`、恢复软链接或回退 legacy。
- legacy-only 操作必须交还 Host Orchestrator，并使用独立 typed authorization；本 Skill 不构造 legacy capability。

## 目标

读取 ISSUE 工单，根据问题分类将其路由到正确责任角色，并判断是否需要升级为 CR。

## 适用场景

- 执行反馈后的问题分流
- 需要决定由谁处理、是否进入变更管理

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
- [ ] ISSUE 工单已存在且基础字段完整
- [ ] 当前状态对象可读取

## 必须读取的输入

- ISSUE 工单
- `process/STATE.md`
- 相关 `CR-*` 或 RUN-EXEC（若存在）

## 知识来源

- ISSUE 的 `category`、`severity`、影响对象
- 当前阶段状态与变更规则
- `CR-*.md` 的字段语义与变更结论口径（仅在需要升级为 CR 时参考）

## 执行步骤

1. 判定 ISSUE 的类别、严重度与影响范围。
2. 选择责任角色或人工接管路径。
3. 若问题影响正式对象或安全边界，则升级为 CR。
4. 回写路由结论与关联对象。

## 输出文件 / 输出模板

输出为路由决策；当需要升级为变更时，复用统一 `CR` 契约，不拥有独立模板。

## 约束

- 只做分类和路由，不做修复
- `env-issue` 必须交人工接管
- 升级为变更时必须复用统一 CR 模板口径

## 验收标准

- [ ] 路由目标明确
- [ ] ISSUE 状态与 owner 已更新
- [ ] 需要升级时已关联 CR

## 不适用边界

- 当前还没有正式 ISSUE 工单
- 问题只是草拟，不需要分流

## Gotchas

- 同症状重复 ISSUE 需要先去重或关联，避免多单并行污染路由结论
- `doc-defect` 不代表低优先级，若影响执行仍可能升级为 CR
