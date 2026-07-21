---
name: coverage-checker
description: >-
  当需要检查测试场景是否被工作流计划完全覆盖时使用。
  触发词包括：覆盖率检查、场景覆盖、未覆盖场景。
  适用场景：计划质量校验的完整性维度。
argument-hint: "docs/product/SCENARIOS.yaml、docs/product/TEST-MATRIX.md 和 process/DEVELOPMENT-PLAN.yaml 路径"
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

交叉比对 `docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md` 和 `process/DEVELOPMENT-PLAN.yaml` 中的场景 / Story / 任务引用，计算覆盖率并列出未覆盖的场景。

## 适用范围

- 适用阶段：CP4 Story / DAG / 并行安全预检，CP7 / CP8 验证覆盖复核
- 对应校验维度：维度 1 — 完整性
- 严重级别：BLOCKING（未覆盖场景视为阻断缺陷）

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
- [ ] `docs/product/SCENARIOS.yaml` 已生成
- [ ] `docs/product/TEST-MATRIX.md` 已生成
- [ ] `process/DEVELOPMENT-PLAN.yaml` 已生成或验证阶段有等价 Story / 测试映射

## 执行约束

- 每个 TC-* 必须被至少一个 Story、验证项或 TEST-MATRIX 行引用
- 覆盖率 = 已覆盖场景数 / 总场景数
- 100% 覆盖时通过，否则为 BLOCKING
- 若仓库提供覆盖检查脚本，可调用脚本辅助；不存在脚本时按 YAML / Markdown 结构化字段人工核对

## Gotchas

- precheck 类场景（type=precheck）通常由 CP0 / CP1 / CP4 / CP7 固定检查覆盖，不一定有显式 Story 引用。需要特殊处理或标记为"隐式覆盖"
- 一个 Story 或验证项可以覆盖多个场景，不能只按单值 `linked_scenario` 判断

## 验收标准

- 输出覆盖率百分比
- 列出所有未覆盖场景的 TC-ID
- 结论写入对应 CP4 / CP7 / CP8 检查摘要，并与 `docs/product/TEST-MATRIX.md` 对齐
