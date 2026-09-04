---
name: release-readiness
description: >-
  当测试报告和评审结论已收敛，需要以低 token 成本准备发布说明、部署检查、
  回滚方案、迁移说明、反馈回流和 CP8 发布就绪判断时使用。
  触发词包括：发布准备、上线检查、回滚方案、RELEASE-NOTES、DEPLOY-CHECKLIST、READY_WITH_RISK。
  适用场景：发布确认前和交付收尾阶段。
argument-hint: "Release Context Capsule、TEST-REPORT.md、REVIEW.md、diff 摘要、配置变化或发布目标"
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

确认“能发布”而不只是“测试通过”。发布阶段必须先形成精简 `Release Context Capsule`，采用 `capsule-first` 读取策略，再按 `release_artifact_profile` 裁剪发布产物，输出可路由的 `release_decision`。

本 Skill 必须遵守 `delivery/rules/AGENT-SKILL-CONTRACT.md`：发布准备默认消费 `process/release/RELEASE-CONTEXT.yaml`、CP result、evidence index 和摘要，不复制完整上游文档。

CP8 必须生成或消费 `fact_diff`，把 CP2 / CR scope 承诺与 CP7 证据逐项对齐。`fact_diff` 只保存 `promise_ref`、`promise` 摘要、`status`、`decision_impact`、`evidence_refs`、`risk_ref`，不得复制完整 checkpoint、测试报告或 evidence 正文。若存在 `MISSING_REQUIRED_EVIDENCE`，`release_decision` 只能是 `NOT_READY`；若存在 `EXECUTED_NEGATIVE_RESULT`、`DEFERRED_FOLLOW_UP` 或 `NEEDS_REVIEW`，不能写成 `READY`，必须是 `READY_WITH_RISK` 或 `NOT_READY`。

发布结论只允许使用：

| release_decision | 含义 | 是否需要独立真实发布授权 |
|---|---|---|
| `READY` | 满足发布条件，可以进入人工发布确认或交付终验 | 否 |
| `READY_WITH_RISK` | 可以发布，但风险已记录并需要风险接受 | 否 |
| `NOT_READY` | 不满足发布条件，不能发布 | 否 |
| `RELEASED` | 真实发布动作已完成，有执行证据 | 是 |
| `FAILED` | 发布动作失败，需要修复、回滚或后续 CR | 是 |

CP8 默认只允许推进到 `READY` / `READY_WITH_RISK` / `NOT_READY`。`RELEASED` / `FAILED` 必须有用户对真实发布、publish、live、外部接口、数据写入或生产操作的独立授权和执行证据；CP8 `approve` 不等于真实发布授权。

风险接受和 waiver 必须服从 `process/policies/WAIVER-POLICY.json`。任何 `WAIVED` 检查项必须有 scope、expiry、approval_ref 和 forces_release_status；需要风险接受的 waiver 必须推动 `READY_WITH_RISK`，不得静默写成 `READY`。未授权 runtime、credential / secret、missing dispatch evidence、runtime-high-risk forbidden path、missing read expansion log、missing evidence 和 false runtime-ready capability claim 不可豁免，发布结论只能是 `NOT_READY` 或阻断。

## 发布产物 profile

`release_artifact_profile` 用来控制发布阶段 token 和文档厚度。

| profile | 适用场景 | 产物形态 | token 策略 |
|---|---|---|---|
| `minimal` | fast-lane、纯文档、小规则修复、无安装 / 迁移 / 发布动作 | CP8 中写发布摘要和逐项 N/A；必要时只更新 `RELEASE-NOTES.md` | 不生成五份长文档 |
| `compact` | standard 默认，普通 Agent / Skill / workflow 交付 | 生成五份 `docs/release/*`，但仅填摘要表和证据路径 | 默认推荐 |
| `full` | 公开版本、安装路径变更、状态迁移、安全权限、真实发布、外部用户升级 | 完整 release notes、安装升级、迁移、回滚、观察和反馈 | 只在高风险启用 |

默认选择规则：

- `workflow_mode=fast-lane` 且无安装 / 权限 / 迁移 / 外部接口影响：`minimal`
- `workflow_mode=standard` 且无破坏性变更：`compact`
- 命中安装路径、状态 schema、命令参数、权限、安全、不可逆迁移、外部用户升级或真实发布：`full`

## 适用场景

- 功能、Agent、Skill、规则或安装脚本已验证，准备合并、交付或发布。
- 涉及配置、环境变量、数据迁移、权限、安全、安装路径或兼容性变化。
- 需要把后续反馈、事故和 follow-up 候选纳入下一轮工作流。

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
- [ ] `docs/quality/TEST-REPORT.md` 已存在且结论可判定，或 Release Context Capsule 写明 N/A / waived 原因。
- [ ] `docs/quality/REVIEW.md` 已存在，且 BLOCKING findings 为 0 或有明确风险接受决策。
- [ ] 变更文件清单、配置变化和发布目标可读取，或已有 diff 摘要。
- [ ] `release_artifact_profile` 已判定。
- [ ] 若项目使用外置 artifact repo，已运行 `meta-flow workspace git-status --project-root .`，并把源码仓库与 artifact 仓库作为同一个发布 / 推送单元检查。

## 必须读取的输入

默认只读取：

- `process/release/RELEASE-CONTEXT.yaml`，若不存在则先生成。
- `process/state/STATE.current.json` 中的当前阶段、active context 和 open risks。
- `docs/quality/TEST-REPORT.md` 的结论段或摘要段。
- `docs/quality/REVIEW.md` 的 findings 摘要。
- diff / 变更文件清单摘要。
- 安装、部署、配置、迁移相关文件的路径和摘要。

按需读取规则：

- 不得默认读取完整 HLD、全部 LLD、完整 TEST-MATRIX、完整 TEST-REPORT、完整 REVIEW 或完整 diff。
- `process/STATE.md`、`process/DEVELOPMENT-PLAN.yaml`、完整 `process/changes/CR-*.md` 和全量 Story 也属于 `do_not_read_by_default`。
- Capsule 字段缺失、证据路径不可读、结论冲突或用户要求深查时，才回读对应上游原文。
- 回读原文后只抽取结论、风险 ID、证据路径和必要一句话摘要，不把长日志、全文 diff 或上游文档正文复制进发布产物。

## Release Context Capsule

发布前必须生成或更新 `process/release/RELEASE-CONTEXT.yaml`，使用 `templates/RELEASE-CONTEXT-TEMPLATE.yaml`。

Capsule 只保存摘要和路径引用，不保存长正文：

| 字段 | 内容 |
|---|---|
| `release_scope` | 版本、Feature / Story、In Scope / Out of Scope、用户可见变化、内部变化 |
| `version_decision` | 当前版本、目标版本、MAJOR / MINOR / PATCH / alpha / beta / rc 判断和原因 |
| `quality_summary` | CP7 / TEST-REPORT / REVIEW 结论，BLOCKER / HIGH 计数，风险接受 ID |
| `fact_diff` | 承诺 vs 交付证据差异表，来源于 CP8 result 或 release context，不复制上游正文 |
| `affected_surface` | 平台、组件、安装 scope、配置、权限、迁移、外部接口、状态 schema |
| `install_validation_summary` | 只记录命令摘要、结果和日志路径，不复制日志 |
| `release_documents` | 五份 release 文档的路径、profile、生成状态和 N/A 原因 |
| `non_authorized_items` | 本轮 CP8 approve 不授权的真实发布、凭据、publish、live、数据写入等事项 |
| `follow_up_summary` | 风险、观察项、反馈分流和 follow-up tracking 候选摘要 |

## 知识来源

- `templates/RELEASE-CONTEXT-TEMPLATE.yaml`
- `templates/RELEASE-NOTES-TEMPLATE.md`
- `templates/DEPLOY-CHECKLIST-TEMPLATE.md`
- `templates/ROLLBACK-TEMPLATE.md`
- `templates/MIGRATION-TEMPLATE.md`
- `templates/FEEDBACK-TEMPLATE.md`

## 执行步骤

1. **生成 Release Context Capsule**：读取最小输入，汇总发布范围、质量结论、风险、影响面、安装验证摘要和待决策项。
2. **生成 CP8 fact_diff**：对齐承诺、交付证据、状态、剩余风险和发布影响；缺失必需证据写 `MISSING_REQUIRED_EVIDENCE` 并强制 `NOT_READY`。
3. **判定 release_artifact_profile**：按 `minimal` / `compact` / `full` 裁剪发布产物，写入 capsule 和 CP8。
4. **判定版本号**：使用 SemVer 或 alpha / beta / rc 规则，将版本号决策写入 capsule、`RELEASE-NOTES.md` 和 CP8 Decision Brief。
5. **整理用户视角 Release Notes**：面向用户说明新增能力、行为变化、修复、破坏性变更、安装升级、迁移、已知问题和回滚方式；不得写成文件 diff 列表；compact profile 只引用 `fact_diff` 和 evidence index。
6. **生成影响面驱动部署检查**：只覆盖 capsule 中受影响的平台、组件和 scope；安装、升级、重复安装幂等、dry-run、卸载 / 回滚按适用性检查。
7. **生成迁移与兼容性判断**：状态 schema、模板字段、配置、安装路径、Agent frontmatter、Skill 输出格式、命令参数和数据结构逐项判定；无迁移时写短 N/A。
8. **生成回滚方案**：说明回滚目标版本、范围、步骤、验证、不可回滚项和责任人；无状态 / 无迁移时写 N/A 原因。
9. **生成反馈与观察计划**：默认并入 `FEEDBACK.md`，记录发布后观察信号、触发阈值和分流；仅 `full` profile 或用户要求时才建议独立 `POST-RELEASE-OBSERVATION.md`。
10. **检查双仓库交付状态**：外置过程仓库模式下，发布准备必须记录 `meta-flow workspace git-status --project-root .` 结果；项目推送必须使用 `meta-flow workspace push --project-root .` 或等价的源码仓库 + artifact 仓库成对推送证据，不能只推开发目录。
11. **输出 release_decision**：`READY` / `READY_WITH_RISK` / `NOT_READY` 可进入 CP8；`RELEASED` / `FAILED` 只在独立真实发布授权后写入。
12. 若反馈或遗留项需要后续 CR 跟踪，只写入 CP8 follow-up tracking 台账候选；`FEEDBACK.md` 不替代正式台账，也不表示候选 CR 已启动。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 | profile 规则 |
|---|---|---|---|
| 发布上下文胶囊 | `process/release/RELEASE-CONTEXT.yaml` | `templates/RELEASE-CONTEXT-TEMPLATE.yaml` | 所有 profile 必须生成 |
| 发布说明 | `docs/release/RELEASE-NOTES.md` | `templates/RELEASE-NOTES-TEMPLATE.md` | minimal 可只写 CP8 摘要；compact / full 生成 |
| 部署检查 | `docs/release/DEPLOY-CHECKLIST.md` | `templates/DEPLOY-CHECKLIST-TEMPLATE.md` | compact / full 生成；minimal 可 N/A |
| 回滚方案 | `docs/release/ROLLBACK.md` | `templates/ROLLBACK-TEMPLATE.md` | compact / full 生成；minimal 可 N/A |
| 迁移说明 | `docs/release/MIGRATION.md` | `templates/MIGRATION-TEMPLATE.md` | compact / full 生成；minimal 可 N/A |
| 反馈回流 | `docs/release/FEEDBACK.md` | `templates/FEEDBACK-TEMPLATE.md` | compact / full 生成；minimal 可 N/A |

## 约束

- 不替代人类批准上线；发布确认必须显式人工决策或预授权条件。
- 不把风险接受伪装成测试通过；接受项必须进入 Decision Brief。
- 不扩大本轮交付范围；后续事项进入 feedback / follow-up / backlog。
- 不默认新增 `CHANGELOG.md`、`INSTALL.md`、`TROUBLESHOOTING.md`、`POST-RELEASE-OBSERVATION.md`；仅 `full` profile 或用户明确要求时生成。
- 不复制完整 TEST-REPORT、REVIEW、TEST-MATRIX、HLD、LLD、日志或全文 diff；只写摘要、计数、风险 ID 和证据路径。
- `FEEDBACK.md` 只记录反馈回流入口；CP8 后续 CR 候选必须进入 `process/changes/CR-*-FOLLOW-UP-TRACKING-YYYY-MM-DD.md`，并由 host-orchestrator 同步 `process/changes/CR-INDEX.json` 与 `process/state/CR-LEDGER.ndjson`。
- 使用外置 artifact repo 时，不得把 `git push` 当前源码仓库当作完整项目推送；必须同时处理源码仓库和 artifact 仓库。`meta-flow workspace push` 默认拒绝 dirty working tree，发现未提交过程文件时应先提交 artifact 仓库。

## CR-058 profile-aware 关闭与发布边界

- G2/G3 必须完成独立 QA、CP8 自动结果和人工门后，才允许 native close；G0 / G1 对不适用的独立 QA 或完整 CP8 控件必须写 profile-aware `N/A` 证据，不能伪造 PASS。GovernanceRiskProfile V2：G2=scope-goal-note；G3=原 G2 完整流程（等价 V1 G2）；只有用户显式选择 G3。
- CP8 前必须读取 cost closure。只有 stage coverage=100%、token proxy 在上限内、去重 gate interaction 在上限内且 unknown leaf paths=0 时，才接受 `PASS_WITH_BASELINE_LIMITATION`；`FAIL` 直接输出 `NOT_READY`。
- CR-057 的 `1,752,000` 是 `authorized_proxy_ceiling`，不是 actual token 基线；发布说明不得声称 actual-to-actual 降本。
- `READY`、`READY_WITH_RISK`、CP8 approve、native close 和 repository cleanliness 都不授权 commit、push、publish、live、production write 或 credential access；真实动作必须有独立 typed authorization。

## 验收标准

- [ ] `process/release/RELEASE-CONTEXT.yaml` 已生成，且不复制长正文。
- [ ] `release_artifact_profile` 已判定，并解释为何不是更厚 / 更薄的 profile。
- [ ] CP8 `fact_diff` 已覆盖承诺、证据、状态、风险和 `decision_impact`；缺失必需证据不会进入 `READY` / `PASS`。
- [ ] `release_decision` 只使用合法枚举，并区分 readiness 与真实 release execution。
- [ ] 发布说明包含版本号决策、用户可见变化、行为变化、破坏性变更、安装升级、迁移、已知问题、回滚方式。
- [ ] 部署检查按受影响平台 / 组件 / scope 生成安装、升级、重复安装幂等和 dry-run 矩阵。
- [ ] 迁移说明覆盖状态 schema、模板字段、配置、安装路径、frontmatter、Skill 输出格式、命令参数和数据结构，或写明短 N/A。
- [ ] 回滚方案可执行，或明确说明无状态 / 无迁移导致 N/A。
- [ ] 发布后观察计划已并入 `FEEDBACK.md`；需要后续 CR 的反馈项已标注为 follow-up tracking candidate。
- [ ] 风险接受、不授权项和真实发布授权边界已进入 CP8 Decision Brief。
- [ ] 外置 artifact repo 模式下，已记录源码仓库和 artifact 仓库的 git 状态；若执行项目推送，已有双仓库推送证据或明确 N/A 原因。

## 不适用边界

- 当前仍在需求、规划或编码阶段。
- 没有准备发布或合并的产物。
- 用户只要求本地实验，不进入交付。

## Gotchas

- 测试通过不代表可以发布；配置、迁移、安装升级、幂等和回滚缺口通常只在发布阶段暴露。
- `READY` 不等于 `RELEASED`；CP8 approve 默认只确认交付就绪，不授权真实发布动作。
- `minimal` 不是跳过发布门；它只减少文档厚度，仍需 capsule、release_decision、风险、不授权项和 CP8 摘要。
- 反馈回流必须分类，否则后续 CR 会把缺陷、新需求、场景缺口和技术债混在一起。
- follow-up tracking 台账才是后续 CR 的执行入口；`FEEDBACK.md` 只是输入来源之一。
- 外置 `process` 是另一个 Git 工作区时，源码仓库干净不代表项目交付完整；过程文件 dirty 或未推送会导致换机器后 CR / checkpoint / ledger 丢失。
