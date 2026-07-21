---
name: review-artifact-protocol
description: >-
  当 review gate 需要统一的 findings / summary 模板和结构校验时使用。
  提供共享模板与轻量校验脚本，供 host-orchestrator 和各 reviewer lane 共用。
argument-hint: "可选：artifact kind(findings/summary)、目标文档路径、评审轮次"
user-invokable: false
status: active
called-by: host-orchestrator, meta-pm, meta-se, meta-dev, meta-qa, meta-doc
---


## vNext 过程引用契约

- `process/...` 是过程仓逻辑引用，不是发布仓中的相对物理路径。
- 首次文件系统 I/O 前必须调用 `meta-flow project resolve-ref --project-root <release-root> --logical-ref <process/...> --format json`。
- 只可瞬时使用成功 JSON 中的 `resolved_path`；不得把绝对路径写入治理文件、Prompt 产物或 Git。
- 命令以退出码 2 返回 BLOCKED 时必须停止；不得自行拼 sibling、去掉 `process/`、恢复软链接或回退 legacy。
- legacy-only 操作必须交还 Host Orchestrator，并使用独立 typed authorization；本 Skill 不构造 legacy capability。

## 目标

集中持有 review gate 的共享产物协议：`Review Findings` 模板、`Review Summary` 模板，以及只做机械结构检查的 validator 脚本。
该协议同时服务 CP3 HLD 多角色讨论和 CP5 LLD 批量决策摘要，并支持 advisor table-first 输入。

本 Skill 必须遵守 `delivery/rules/AGENT-SKILL-CONTRACT.md`：review artifact 默认消费 context `allowed_reads`、evidence index 和 summary，不复制完整 HLD / LLD / TEST-REPORT / diff。

## 适用场景

- `host-orchestrator` 组织结构化评审，需要下发统一 findings / summary 模板
- reviewer lane 产出 findings 前，需要确认字段、章节和锚点口径
- CP3 HLD 前置讨论需要区分“方案形成输入”和“HLD 后评审意见”
- 聚合 summary 前，需要先做一次轻量结构校验

## 必须读取的输入

- 当前待评审对象路径或 context / packet `allowed_reads` 中的对象摘要
- reviewer lane / reviewer 标识
- 当前轮次
- 已填写的 findings 或 summary 文档
- evidence index / CP result refs（若存在）

## 知识来源

- `skills/review-artifact-protocol/templates/REVIEW-FINDINGS-TEMPLATE.md`
- `skills/review-artifact-protocol/templates/REVIEW-SUMMARY-TEMPLATE.md`
- `skills/review-artifact-protocol/scripts/validate_review_artifact.py`

## 执行步骤

1. 根据当前产物类型选择 findings 或 summary 模板。
2. 填写 frontmatter、章节与表格内容；不得删减模板要求的结构标记。
   - CP3 HLD 讨论至少覆盖 `lane-product`、`lane-architecture`、`lane-quality` 三类视角；`lane-docs` 的可读性 / 可维护性可作为汇总检查项纳入。
   - CP3 HLD 方案形成输入必须优先使用 advisor 表格：`Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch`。
   - CP3 HLD 后评审意见必须单独标记为 `post_hld_review`，不得倒填为方案形成前输入。
   - Summary 必须给出推荐决策、备选方案、风险和用户需决策事项，供 host-orchestrator 汇入 Decision Brief。
3. Findings 和 Summary 只写问题、严重度、证据路径、hash / anchor、影响和建议；不得把完整待评审对象、完整 diff、完整测试日志或完整 policy 全文复制进 review artifact。
4. 在提交给 `host-orchestrator` 聚合前，运行 validator 脚本做结构检查：

```bash
uv run --python 3.11 python <skill-root>/scripts/validate_review_artifact.py <artifact-path> --kind findings
uv run --python 3.11 python <skill-root>/scripts/validate_review_artifact.py <artifact-path> --kind summary
```

5. validator 返回 `OK` 后再进入 findings 聚合或 summary 决策。

## 输出文件 / 输出模板

| 文件 | 路径 | 角色 |
|---|---|---|
| Findings 模板 | `skills/review-artifact-protocol/templates/REVIEW-FINDINGS-TEMPLATE.md` | reviewer lane 共用结构 |
| Summary 模板 | `skills/review-artifact-protocol/templates/REVIEW-SUMMARY-TEMPLATE.md` | `host-orchestrator` 聚合结构 |
| Validator | `skills/review-artifact-protocol/scripts/validate_review_artifact.py` | frontmatter / marker / 锚点机械校验 |

## 约束

- 只做**结构协议**复用，不承载语义评审规则
- validator 只校验 frontmatter、标题/章节 marker 和固定锚点，不做结论裁决
- 模板属于共享 Skill 私有资产，不再放到 `delivery/` 顶层公共目录
- advisor table-first 只定义输入结构，不新增 canonical agent；具体调度仍由 host-orchestrator 决定并记录子 agent 调度证据
- discussion log 用于审计和恢复，不替代正式 HLD、ADR、Decision Brief 或 Review Summary
- `process/STATE.md`、完整 Story LLD、完整 TEST-REPORT、完整 REVIEW 和完整 diff 必须属于 `do_not_read_by_default`

## 验收标准

- [ ] findings / summary 模板都位于本 Skill 目录下
- [ ] validator 能校验 findings / summary 两类文档
- [ ] Claude Code / Codex 安装后，模板和 validator 会随 Skill 一起复制

## Gotchas

- findings / summary 的正文可以扩展，但 frontmatter 必填字段与 marker 不能删
- 该 Skill 提供的是共享协议，不替代 `host-orchestrator` 的 reviewer dispatch 和严重度聚合规则
- 方案形成前输入和 HLD 后评审意见混写，会导致 CP3 追溯失真，必须拆分记录
- advisor 表格缺少 `When to switch` 时，推荐方案没有可操作回退条件，应视为不完整输入
- 若平台安装时未安装本 Skill，就不能假定 validator 脚本在目标环境中可用
