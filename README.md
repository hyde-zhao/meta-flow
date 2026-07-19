# Meta Flow 元工作流

> 通用 Agent/Skill 工作流产物工厂 — 从需求到交付的全流程编排。

## vNext：默认使用每项目独立双仓与轻量 Work

Meta Flow 的新默认不再是共享 artifact worktree、双 leg 或每项变化都跑 CP0-CP8。每个项目拥有一个发布库和一个独立过程库；发布库用 tracked 的 `.meta-flow/workspace.yaml` 定位 sibling `<project>-process`，过程库用 `.meta-flow-process.yaml` 反向绑定发布库。默认 `route_mode=sibling-binding`，不创建 `process` 软链接；因此项目 A 切分支不会改变项目 B 看到的过程文档。

`project init` 会复用已有发布 Git 根；若目标路径不存在或为空目录，则只在显式 `--apply` 时初始化本地 `main` 发布库。非空非 Git 目录始终 fail closed。当前 `anchor=workspace_parent` 只支持同一父目录下的 sibling 双仓，不会扫描其他 sibling，也不接受绝对路径或 `..`；非 sibling 布局需要未来独立设计的 `workspace_root` 锚点，当前直接阻断。

```bash
# 1. 只读预览；默认不修改文件
meta-flow project init --project-root . --project-id demo

# 2. 用户确认后才在本地建立独立过程仓与双向 binding，不创建软链接
meta-flow project init --project-root . --project-id demo --apply

# 只有仍需运行字面量访问 process/... 的 legacy Agent/Skill 时才选择兼容链接
meta-flow project init --project-root . --project-id demo --process-link-mode relative-symlink --apply

# 3. 确认需求后解释 Work/CR 与 G0/G1/G2 判定
meta-flow work classify --change-kind documentation --touched-path-count 1

# 4. 只读一个 Work 或最多五个直接引用的 Project/Phase/Work 对象
meta-flow work status --project-root . --work-id W-001
meta-flow project query --project-root .
```

日常变化默认用 Work；公共契约、架构、安全权限、不可逆迁移、生产写、正式发布、强审计、风险接受和跨阶段重构才升级正式 CR/G2。G0/G1 只生成当前 Work 必要的 `REQUEST.md`、`WORK.yaml`、usage/handoff/result，不强制八份产品基线、全量 HLD/LLD 或 CP0-CP8。

| 档位 | 上限 | 评审与验证 |
|---|---|---|
| G0 | `8 reads / 8 writes / 3 check groups / 32k token` | 无独立设计评审；目标测试/静态检查 + diff/status |
| G1 | `20 / 24 / 8 / 96k` | 最多一次 Work 范围轻量评审；目标测试 + 必要构建/定向检查 |
| G2 | 每项显式批准 | HLD/ADR、人工设计门、独立 QA 和经批准的全量验证 |

提交和推送也按仓库独立处理：`meta-flow repository commit|push` 默认只做 dry-run，真实动作必须提供与单仓计划和 exact OID 匹配的 typed authorization；一侧成功另一侧失败时报告 `PARTIAL`，不伪装原子性，也不自动回滚成功一侧。

项目或关键 Phase 完成后，`meta-flow retrospective` 生成价值、规范/证据、质量/恢复、流动效率、token/context、Meta Flow 适配性六维复盘。`meta-flow evolution` 把事实确认、建议批准、实现启动和发布授权拆开；复盘报告不能直接修改 Meta Flow，也不能递归触发下一轮自进化。

## 目录结构

| 目录 | 用途 |
|------|------|
| `delivery/` | **meta-flow 自身可独立交付的包**（可推送为独立 Git 仓库）；外部 production 项目的交付出口需按目标 README/docs 或用户确认路由 |
| `delivery/agents/` | 交付 Agent 定义（安装脚本从此读取，`<name>.md`） |
| `delivery/skills/` | 交付 Skill 定义（结构为 `<name>/SKILL.md`；模板位于 `<name>/templates/`） |
| `delivery/rules/` | 平台规则源（`AGENTS.md` 唯一源；claude 安装时生成 `CLAUDE.md`） |
| `delivery/scripts/` | 安装脚本入口（`install.py` / `install.sh` / `install.ps1`）；需随 Skill 一起安装的私有脚本应放在对应 `delivery/skills/<skill>/scripts/` 下 |
| `scripts/` | 仓库级检查/构建脚本（不随 `delivery/` 一起安装到目标平台） |
| `.agents/agents/` | 元工作流引擎 Agent 定义（不参与安装） |
| `.agents/skills/` | 元工作流引擎 Skill 定义（不参与安装） |
| `.input/` | 只读输入目录（用户提供的原始材料） |
| `<project>/.meta-flow/` | vNext workspace binding 与项目级安装器状态；`workspace.yaml` 必须跟踪，`INSTALL-MANIFEST.yaml` 是本机状态且必须忽略 |
| `~/.meta-flow/` | 用户级安装器状态目录（仅保存 user-scope 安装 manifest，不作为当前元工作流运行态输出目录） |
| `docs/` | 公开文档入口；源码仓库跟踪用户可见文档，内部设计 / 质量 / 发布审查文档通过本地 symlink 指向外置 artifact repo（生产项目按目标 README/docs 约定或用户确认路由） |
| `docs/product/` | 场景、需求、测试矩阵、Story Map、MVP 范围、发布切片和 backlog |
| `docs/design/` | 蓝图、领域图、依赖图、HLD 和架构决策 |
| `docs/features/` | Feature 级 DESIGN.md / TEST-PLAN.md / TASKS.md |
| `docs/quality/` | 测试策略、测试报告、质量评审和修复摘要 |
| `docs/release/` | 发布说明、部署检查、回滚、迁移和反馈入口 |
| `process/` | 运行时文档（gitignored，STATE.md / REQUEST.md / plans / stories / CR / discussions / checks 等） |
| `process/discussions/` | CP2 / CP3 讨论日志（gitignored，用于人类审计和中断恢复，不替代正式产物） |
| `process/checks/` | 自动检查点结果（gitignored，CP0-CP8 自检证据） |
| `process/context/` | 阶段上下文胶囊 / context pack（gitignored，CP2/CP3/CP5/CP6/CP7/CP8 的默认读取入口，用于减少子 agent token 消耗） |
| `process/checkpoints/` | 人工检查点审查稿（gitignored，CP2/CP3/CP5/CP8 Decision Brief、checklist 与审查结果；CP4 仅自动预检） |

## 输出隔离原则

所有由元工作流产生的文件统一按层输出。meta-flow 自身改进使用当前仓库 `delivery/`；外部 production 项目必须先读取目标 `README.md` / `README.*` / `docs/` 的交付约定，若无约定则先给出建议并等待用户确认。

分层原则：

- `docs/` 承载公开文档入口：源码仓库跟踪 `docs/release/RELEASE-NOTES.md` 和 `docs/USER-MANUAL.md` 等用户可见文档。
- 内部设计、Feature、质量、发布审查、修改记录和偏好类文档归档到 artifact repo，并可通过本地 ignored symlink 保持 `docs/design`、`docs/quality` 等旧路径可读。
- 源码仓库还保留根 README、`delivery/README.md`、`delivery/doc/USER-MANUAL.md` 和平台契约等产品/安装入口。
- `process/` 承载运行过程文档：状态、计划、Story 执行态、讨论日志、handoff、CR、自动检查结果。
- vNext binding-only 适用于 G0/G1/G2，默认不创建 `process` 入口，直接从 workspace binding 解析独立过程仓。只有 legacy 项目，或当前 G2/正式 CR 的人工门显式选择 legacy/shared-artifact 扩展控制项时，`process/` 才作为兼容运行态入口；旧 shared-artifact 外置模式下它是指向 `<artifact-root>/process/<project-name>/` 的软链接。
- `process/context/` 承载阶段上下文胶囊 / context pack：下游 Agent、人工门禁、验证和发布准备默认先读 context pack，只读取 `allowed_reads`；只有缺失、冲突、字段不足、人工审计或深度评审时才展开读取完整正式文档，并记录允许枚举内的全文读取理由。
- Agent / Skill 共享瘦身契约写在 `delivery/rules/AGENT-SKILL-CONTRACT.md`，目录与分区契约写在 `delivery/rules/DIRECTORY-CONTRACT.md` / `.yaml`。功能 Agent 必须先读阶段 context pack 或 Story packet，默认机器状态入口是 `process/state/STATE.current.json`，默认文件系统发现入口是 `process/current/CURRENT.json`；`process/STATE.md`、`process/DEVELOPMENT-PLAN.yaml`、完整 CR、全量 Story LLD、`process/archive/**`、完整 TEST-REPORT / REVIEW / diff 属于 `do_not_read_by_default`。Handoff 只传 `context_ref` / `story_packet_ref` / `evidence_ref` / `result_ref`，真实执行证据写入 ledger。
- `process/checkpoints/` 承载人工确认态：CP2 / CP3 / CP5 / CP8 Decision Brief、checklist 和人工审查结果。
- 旧项目中的 `process/USE-CASES.md`、`process/HLD.md`、根目录 `checkpoints/CP*.md` 等只作为 legacy fallback 读取；新生成默认写入 `docs/...` 和 `process/checkpoints/...`。

核心长期产物的 canonical 路径包括：`docs/product/SCENARIOS.yaml`、`docs/product/MVP-SCOPE.md`、`docs/design/BLUEPRINT.md`、`docs/release/DEPLOY-CHECKLIST.md`。

## Legacy：共享 Artifact 外置路由

> 本节保留给尚未迁移的项目和历史 CR 审计。新项目应使用上方 `project init` 的独立过程库，不应新增 shared artifact worktree、project integration branch、双 leg 或 aggregate。

Meta Flow 支持把过程文件和过程文档从源码仓库中外置。`process/` 默认目标形态是：

```text
<project-root>/process -> <artifact-root>/process/<project-name>
```

初始化或迁移时必须先创建真实目录，再建立软链接，并写入：

```text
process/.meta-flow-process.yaml
process/`STATE.current.json.artifact_routing_ref` 与 `process/.meta-flow-process.yaml`
```

健康检查会在读取状态、CR tracking 和推进检查点前验证 `process` 路由。若发现 `process` 缺失、软链接断裂、`process/STATE.md` 缺失、项目名不匹配或路由元数据冲突，当前工作流必须中断；用户需要提供有效 `artifact_root` / `process_root` 后继续，不得静默重建新的 `STATE.md`。

路由记录必须可迁移，不能写入 `/home/...` 这类设备相关绝对路径。`STATE.current.json.artifact_routing_ref` 与 `process/.meta-flow-process.yaml` 与 `process/.meta-flow-process.yaml` 使用锚点 + 相对路径：

- `artifact_root`：相对 `project_root`，例如 `../meta-flow-artifacts`
- `project_process_root`：相对 `artifact_root`，例如 `process/meta-flow`
- `link_path`：相对 `project_root`，例如 `process`

同一项目换设备后，只要源码仓库和 artifact 仓库保持相同相对布局，路由记录无需改写；布局变化时重新执行 `meta-flow workspace link --artifact-root <relative-artifact-root> --project-name <project-name>`。

当前仓库在迁移前允许 `routing_mode=local-directory` 兼容模式。迁移到软链接后，`.gitignore` 应使用 `/process`；不要使用 `/process/`，因为带尾斜杠的规则不会忽略 symlink 本身。

路由检查命令：

```bash
meta-flow workspace check
meta-flow workspace git-status --project-root .
meta-flow workspace push --project-root .
meta-flow doctor
meta-flow doctor tokens --project-root .
meta-flow doctor context --project-root .
meta-flow doctor artifacts --project-root .
meta-flow state check --project-root .
meta-flow cr check --project-root .
meta-flow context build --stage CP6 --profile standard-code --cr CR-101 --project-root .
meta-flow context check --context process/context/CP6-CR101.context.json --project-root .
meta-flow context build-story-packet --story process/stories/STORY-CR123-S01.md --stage CP6 --project-root .
meta-flow context check-story-packet --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --project-root .
meta-flow context sufficiency-check --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json
meta-flow context read-log --path process/STATE.md --reason human_audit --stage CP6 --agent meta-dev --context-ref process/context/stories/STORY-CR123-S01.CP6.work-packet.json --project-root .
meta-flow context read-log-check --project-root .
meta-flow cp result-check --result process/checks/CP6-STORY-CR123-S01.result.json --project-root .
meta-flow cp render-summary --result process/checks/CP6-STORY-CR123-S01.result.json
meta-flow cp ledger-append --result process/checks/CP6-STORY-CR123-S01.result.json --project-root .
meta-flow event check --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint
meta-flow story return-check --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .
meta-flow story evidence-index --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .
meta-flow story verify-packet --from-return process/returns/STORY-CR123-S01.CP6.return.json --story process/stories/STORY-CR123-S01.md --project-root .
meta-flow story plan-check --project-root .
meta-flow design delta-check --delta process/design-deltas/STORY-CR123-S01.delta.json --project-root .
meta-flow design delta-check --delta process/design-deltas/STORY-CR123-S01.delta.json --require-merged --project-root .
meta-flow validation run --cr CR-155 --profile real-lake-readonly --reruns 2 --project-root .
meta-flow feature build --project-root .
meta-flow feature check --project-root .
meta-flow feature trace --project-root .
meta-flow module init --project-root .
meta-flow check module-boundaries --project-root .
meta-flow check imports --project-root .
meta-flow check architecture-fitness --project-root .
meta-flow check risk-rings --changed-files quant_lab/trading/order.py --project-root .
meta-flow capability check --artifact README.md --project-root .
meta-flow concept check --changed-files quant_lab/engine/contracts.py --project-root .
meta-flow identity check --project-root .
meta-flow gate classify --changed-files README.md
meta-flow gate classify --impact QMT credential runtime
meta-flow gate plan --profile process-lite --project-root .
meta-flow governance init --project-root .
meta-flow governance truth-map-check --project-root .
meta-flow governance retention-check --project-root .
meta-flow policy list --project-root .
meta-flow policy check --artifact process/changes/summaries/CR-101.summary.json --project-root .
meta-flow next
```

外置 artifact 仓库启用后，项目交付包含两个 Git 工作区：源码仓库和 artifact 仓库。提交 / 推送时必须把两者作为同一个交付单元处理：

- 提交前运行 `meta-flow workspace check --project-root .` 和 `meta-flow workspace git-status --project-root .`。
- 源码改动提交到开发目录仓库；`process/`、checkpoint、ledger、handoff、context、CR 和内部归档提交到 artifact 仓库。
- 推送项目时使用 `meta-flow workspace push --project-root .`，或提供等价的源码仓库 + artifact 仓库成对 `git push` 证据。
- `meta-flow workspace push` 默认拒绝 dirty working tree；如果 artifact 仓库还有未提交过程文件，必须先提交，避免只推源码导致换机器后状态丢失。

`meta-flow next` 只输出可直接复制的下一步准确提示词，例如 `approve`、`修改: <具体修改点>`、`reject`、`执行下一步: <具体动作>` 或 `处理阻塞: <具体处理方式>`；不会要求用户只回复“同意”“继续”等模糊词。

Context-budgeted 端到端回归 fixture 位于 `evals/fixtures/context-budgeted-meta-flow/`，用于验证 `STATE.current.json -> CR summary -> context pack -> Story packet -> Story return -> evidence index -> CP result -> checkpoint ledger` 这条链。对应测试为 `tests/test_context_budgeted_flow_e2e.py`，会证明默认 `allowed_reads` 不包含 `process/STATE.md`、`process/DEVELOPMENT-PLAN.yaml`、完整 CR 或全量 Story LLD。

MF-016 增加了上下文足够性和实际扩展读取审计。Story packet 除了 token budget 和 deny-default，还必须能说明 Feature context、CR delta、dependency inputs、读写边界、acceptance、verification plan、authz policy refs 和 expected return packet；`meta-flow context sufficiency-check` 会检查这些槽位。所有 deny-default 全文读取应通过 `meta-flow context read-log` 写入 `process/state/READ-EXPANSION-LEDGER.ndjson`，再由 `meta-flow context read-log-check` 与 `meta-flow doctor context` 校验；Context Doctor 会输出高频展开文件、Feature、原因分布、缺失槽位和摘要更新建议。

MF-017 增加 Failure Routing / Waiver Governance。`meta-flow failure route-check --result <CP-result> --project-root .` 校验 `route_on_fail` 是否属于固定动作枚举，并确保高严重度失败可路由；`meta-flow waiver check --result <CP-result> --project-root .` 校验 waiver 的 scope、expiry、approval_ref、forces_release_status 和不可豁免项。不可豁免项包括未授权 runtime access、credential / secret exposure、missing dispatch evidence、runtime-high-risk forbidden path、missing read expansion log 和 false runtime-ready capability claim；风险接受型 waiver 不得静默 PASS，必须进入 `PASS_WITH_RISK` 或 `READY_WITH_RISK`。

新工作区链接命令：

```bash
meta-flow workspace link --artifact-root ../meta-flow-artifacts --project-name meta-flow
```

当前 `docs/` 不再整体外置。它分为公开文档和内部归档文档：

```text
<project-root>/docs/release/RELEASE-NOTES.md  # 源码跟踪
<project-root>/docs/USER-MANUAL.md            # 指向 delivery/doc/USER-MANUAL.md
<project-root>/docs/design                    # 本地 ignored symlink -> <artifact-root>/docs/<project-name>/design
<project-root>/docs/features                  # 本地 ignored symlink -> <artifact-root>/docs/<project-name>/features
<project-root>/docs/quality                   # 本地 ignored symlink -> <artifact-root>/docs/<project-name>/quality
```

当前仓库对应的可迁移记录示例：

```text
<project-root>/docs/design
  -> <artifact-root>/docs/meta-flow/design
  where artifact_root = ../meta-flow-artifacts
<project-root>/docs/quality
  -> <artifact-root>/docs/meta-flow/quality
  where artifact_root = ../meta-flow-artifacts
```

源码仓库保留的文档入口为根 `README.md`、`docs/README.md`、`docs/release/RELEASE-NOTES.md`、`docs/USER-MANUAL.md`、`delivery/README.md`、`delivery/doc/USER-MANUAL.md` 和 `delivery/doc/PLATFORM-CONTRACTS.yaml`；`docs/` 下的设计、Feature、质量、内部发布审查、修改记录和偏好类过程文档由 artifact repo 跟踪。

```
├── process/                     # 运行时文档（默认建议 gitignore）
│   ├── STATE.md
│   ├── REQUEST.md
│   ├── INPUT-INDEX.md
│   ├── CLARIFICATION-LOG.md
│   ├── DEVELOPMENT-PLAN.yaml     # Story 管理机器真相源
│   ├── STORY-BACKLOG.md          # 可选 legacy / generated view
│   ├── discussions/
│   ├── checks/
│   ├── context/
│   │   └── stories/              # Story Context Contract / Work Packet / Verify Packet
│   ├── returns/                  # Story Return Packet，记录 agent 实际完成内容
│   ├── evidence/                 # Evidence Index，索引命令、文件、风险和 waiver
│   ├── design-deltas/            # Story 对 Feature DESIGN / ADR / HLD 的设计回写请求
│   ├── policies/
│   │   ├── READ-POLICY.json
│   │   ├── ARTIFACT-BUDGETS.json
│   │   ├── SOURCE-OF-TRUTH-MAP.yaml
│   │   └── RETENTION-POLICY.json
│   ├── state/
│   │   ├── STATE.current.json
│   │   ├── CR-LEDGER.ndjson
│   │   ├── CHECKPOINT-LEDGER.ndjson
│   │   ├── HANDOFF-LEDGER.ndjson
│   │   ├── AGENT-DISPATCH-LEDGER.ndjson
│   │   ├── GATE-LEDGER.ndjson
│   │   └── RUN-LEDGER.ndjson
│   ├── checkpoints/
│   ├── changes/
│   └── stories/                  # Story 卡片、LLD 和 Story 级 IMPLEMENTATION.md
├── docs/                        # 长期可交付文档（production 项目可按目标约定改路由）
│   ├── product/
│   │   ├── USE-CASES.md
│   │   ├── REQUIREMENTS.md
│   │   ├── SCENARIOS.yaml
│   │   ├── TEST-MATRIX.md
│   │   ├── STORY-MAP.md
│   │   ├── MVP-SCOPE.md
│   │   ├── RELEASE-SLICES.md
│   │   └── BACKLOG.md
│   ├── design/
│   │   ├── BLUEPRINT.md
│   │   ├── DOMAIN-MAP.md
│   │   ├── DEPENDENCY-MAP.md
│   │   ├── HLD.md
│   │   └── ARCHITECTURE-DECISION.md
│   ├── features/<feature>/
│   │   ├── DESIGN.md
│   │   ├── TEST-PLAN.md
│   │   ├── TASKS.md
│   │   └── IMPLEMENTATION.md     # 复杂 / 高风险 Feature 的实现执行证据
│   ├── quality/
│   │   ├── TEST-STRATEGY.md
│   │   ├── VERIFICATION-REPORT.md
│   │   ├── TEST-REPORT.md
│   │   ├── REVIEW.md
│   │   └── FIXES.md
│   └── release/
│       ├── RELEASE-NOTES.md
│       ├── DEPLOY-CHECKLIST.md
│       ├── ROLLBACK.md
│       ├── MIGRATION.md
│       └── FEEDBACK.md
├── process/
│   └── release/
│       └── RELEASE-CONTEXT.yaml
└── delivery/                    # meta-flow 自身最终交付物（production 项目不默认使用）
    ├── README.md
    ├── doc/
    ├── agents/
    ├── skills/
    ├── rules/
    └── scripts/
```

安装测试优先使用全局命令或 `uv run`：

```bash
uv run --python 3.11 meta-flow install codex --scope project --component full --project-dir . --dry-run
uv run --python 3.11 python delivery/scripts/install.py codex --dry-run
```

## Workflow Eval 与 Prompt Bundle

Meta Flow 同时支持纯代码项目和 workflow / prompt-skill / mixed 项目。两类判断必须分开：

- `engagement_mode` 只判断当前是在优化 meta-flow 自身，还是在为 production 目标项目交付。
- `STATE.current.json.target_project_profile_ref` 判断目标项目类型：`code-project`、`workflow-product`、`agentic-code-product`、`mixed` 或 `unknown`。
- Story / 交付对象用 `validation_target.sut_type` 判断 CP7 验证层：`code-project`、`generated-workflow`、`prompt-skill-workflow`、`meta-flow-core-code`、`agentic-code-product` 或 `mixed`。

纯代码项目默认继续使用目标项目原生测试、构建、静态检查和 quality-review，不强制 workflow eval。generated workflow、prompt-skill、meta-flow-core-code、agentic-code-product 和 mixed 对象必须提供 workflow eval / prompt bundle 证据，或在 CP7 中写明 `WAIVED` / `BLOCKED` 原因。

本地 deterministic eval 命令：

```bash
meta-flow eval validate --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml
meta-flow eval run --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/generated-workflow-basic
meta-flow eval suite-health --runs process/evals/runs --out docs/quality/EVAL-SUITE-HEALTH.md
meta-flow eval run --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/runtime-workflow-basic
meta-flow eval runtime-run --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --sample RT-GENERIC-FULL-20260617 --platform codex --workspace evals/fixtures/runtime-workflow-basic/runtime/workspace-basic --mode collect --out process/evals/runtime-run
meta-flow eval suite-health --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --runs process/evals/runs --out docs/quality/EVAL-SUITE-HEALTH.md
meta-flow eval feedback sync --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/feedback/raw
meta-flow eval feedback normalize --in process/evals/feedback/raw --out process/evals/feedback/run-exec
meta-flow eval feedback triage --runs process/evals/feedback/run-exec --out process/evals/feedback/triage
meta-flow eval release-check --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --runs process/evals/runs --profile release --triage process/evals/feedback/triage --format json --json-out process/evals/release-check.json
```

核心契约：

| 契约 | 路径 | 用途 |
|---|---|---|
| Workflow eval schema | `evals/contracts/WORKFLOW-EVAL.schema.yaml` | 定义 suite、SUT、trace policy 和 grader |
| Prompt bundle schema | `evals/contracts/PROMPT-BUNDLE.schema.yaml` | 定义 prompt/rules/agent/skill/template/rubric 的引用、hash、兼容性和回滚 |
| Case registry schema | `evals/contracts/CASE-REGISTRY.schema.yaml` | 定义 case 生命周期、覆盖类别、grader 引用和期望结果 |
| Runtime sample registry schema | `evals/contracts/RUNTIME-SAMPLE-REGISTRY.schema.yaml` | 定义已有运行 workspace 样本、profile、阶段产物、trace chain 和 expected BLOCKED 语义 |
| Feedback triage schema | `evals/contracts/FEEDBACK-TRIAGE.schema.yaml` | 定义 normalized RUN-EXEC、triage、ISSUE_DRAFT 和 GAP 输出 |
| Eval backlog schema | `evals/contracts/EVAL-BACKLOG.schema.yaml` | 定义 feedback/GAP 驱动的 eval backlog 与关闭规则 |
| Run evidence | `process/evals/runs/<run-id>/` | 本地执行证据，供 CP7 / CP8 消费 |
| Suite health | `docs/quality/EVAL-SUITE-HEALTH.md` | 长期质量状态摘要 |

通用 runtime / feedback / mutation / install eval 能力：

| 能力 | 命令 | 边界 |
|---|---|---|
| Runtime artifact grader | `meta-flow eval run --eval <WORKFLOW-EVAL.yaml>` 中的 `type: runtime_artifact` | 只读取已有运行工作区；支持 `sample_registry` / `sample_ids` / `profile=partial|full|regression`，检查目录、STATE phase、Skill 调用链、Gate、阶段顺序、内容密度、空文件 / 模板残留、delivery、trace chain、coverage 和表格；不负责真实执行 Agent |
| Runtime eval runner | `meta-flow eval runtime-run --eval <WORKFLOW-EVAL.yaml> --sample <id> --platform codex|claude --mode dry-run|manual-handoff|collect` | 生成 RUN-EXEC 和 runtime artifact manifest；`collect` 只收集已有 workspace 的证据路径，不判分、不启动 Agent，输出可直接交给 runtime_artifact grader |
| Feedback source / triage | `meta-flow eval feedback sync|normalize|triage|analyze` | source 先同步为 raw，再标准化为 RUN-EXEC，最后 triage 为 `ISSUE_DRAFT` / `GAP` / `BACKLOG` / `ENVIRONMENT` / `USAGE` / `DUPLICATE` / `NO_ACTION`；`local` 默认可读，`git` / `gitlab` 需要显式 `--allow-git-read` |
| Mutation eval | `meta-flow eval mutate --eval <WORKFLOW-EVAL.yaml> --fixture <valid-fixture> --mutation <type> --out <generated-negative-dir>` | 生成确定性负例，用来验证 grader 是否能抓住缺字段、坏表格、错 prompt hash、缺 artifact path、secret pattern、缺 runtime artifact 等问题 |
| Install mapping | `meta-flow eval install-check --eval <WORKFLOW-EVAL.yaml>` 或直接传 `--platform/--agent/--expected-skill --target --platform-contracts` | 复用安装 manifest、dry-run 输出或 installed root 做检查；可按 `PLATFORM-CONTRACTS.yaml` 检查真实 agent/skill/rules 路径和 stale / forbidden 项 |
| Suite health | `meta-flow eval suite-health --runs <runs-dir> --triage <triage-dir> --feedback-metrics <run-exec-dir>` | 健康趋势报告，统计 runtime、feedback、RUN-EXEC、ISSUE/GAP/backlog、flaky 和覆盖趋势；不承担发布门禁 |
| Release check | `meta-flow eval release-check --eval <WORKFLOW-EVAL.yaml> --runs <runs-dir> --profile release --triage <triage-dir>` | 独立发布判定；输出 `release_decision=PASS|PASS_WITH_RISK|BLOCKED`，支持 JSON，检查 blocking / required grader、prompt bundle hash、runtime sample、case registry 质量语义、未闭环 P0 GAP / blocking ISSUE 和最近运行退化 |
| Eval backlog | `meta-flow eval backlog list/check/close --backlog <EVAL-BACKLOG.json|yaml>` | 未覆盖 ISSUE 应进入 backlog；关闭必须绑定 regression asset |

Promptfoo、DeepEval、Langfuse 和 Garak 只作为可选 adapter，默认 disabled。任何网络、凭据、trace 上传、外部模型调用、publish、live 或 production 写入都必须单独形成 `runtime_authorization` 决策项；`approve` 或“跳过人工审批”不等于授权这些真实外部动作。

## `~/.meta-flow` 目录说明

`~/.meta-flow/` 当前不承载 Meta Flow 的运行态文档，也不是 `process/`、`process/checks/`、`process/checkpoints/` 或交付出口的替代目录。当前规则要求元工作流运行态仍写入仓库根目录下的 `process/`、自动检查结果写入 `process/checks/`、人工审查稿写入 `process/checkpoints/`；交付态按 engagement mode 路由，meta-flow 自身改进写当前仓库 `delivery/`，外部 production 项目按目标项目约定或用户确认输出。

当前实现按 scope 隔离安装状态：项目级安装写入目标项目的 `.meta-flow/INSTALL-MANIFEST.yaml`，用户级安装才写入 `~/.meta-flow/delivery/doc/INSTALL-MANIFEST.yaml`。manifest 记录已安装的平台、scope、安装时间、canonical commit、目标路径和卸载所需的 remove path；对应 scope 的 `meta-flow uninstall <platform>` 与 `delivery/scripts/install.py uninstall <platform>` 依赖各自 manifest 精确卸载。

因此：

1. 若仍需要通过安装器执行项目级精确卸载，应保留目标项目的 `.meta-flow/INSTALL-MANIFEST.yaml`；该本机状态文件应保持 gitignored。
2. 若仍需要执行用户级精确卸载，应保留 `~/.meta-flow/delivery/doc/INSTALL-MANIFEST.yaml`。
3. 删除对应 manifest 会丢失该 scope 的安装记录，但不会授权删除已安装资产；`~/.meta-flow/` 仍不属于任何项目的运行态文档或交付出口。

## Python 环境规范（uv）

当前仓库对 Python 运行环境采用 `uv` 作为统一工具链，并已提供 `pyproject.toml` / `uv.lock` 与 `meta-flow` console script。因此本阶段的执行约束是：

1. 使用 `uv` 安装和选择 Python 解释器，不以系统 Python 作为默认入口。
2. 运行仓库内 Python 脚本时，优先使用 `uv run --python <version> python <script>`；安装入口优先使用 `meta-flow install`。
3. 一次性工具与临时依赖优先使用 `uvx` 或 `uv run --with <package>`，不把裸 `pip install` 作为日常流程。
4. 安装到目标项目的 uv 规范统一通过 `delivery/rules/AGENTS.md` 传播（claude 平台安装时生成 CLAUDE.md）。

示例：

```bash
uv python install 3.11
uv tool install --editable .
meta-flow install codex --scope user --component rules
meta-flow install codex --scope project --component full --project-dir /path/to/project
meta-flow uninstall codex --scope project --project-dir /path/to/project
meta-flow install codex --help
meta-flow uninstall codex --help
# 从项目根运行
uv run --python 3.11 python delivery/scripts/install.py claude --dry-run
# 或从 delivery/ 目录运行（delivery 作为独立仓库时）
cd delivery && uv run --python 3.11 python scripts/install.py claude --dry-run
```

## 开发节奏

1. `host-orchestrator` 初始化请求并写入 CP0 自动检查结果。
2. `host-orchestrator` 将需求澄清阶段委托给 `meta-pm`。用户直接与 `meta-pm` 通过 Scenario Gray Areas 识别 3-4 个会影响交付的场景灰区，选择 1-3 个重点讨论；未选项进入 Deferred Ideas。随后输出场景 / 需求，写入 CP1 / CP2 自动检查结果；用户确认“可提交给 host-orchestrator 汇总”后交还，host-orchestrator 生成 `process/context/CP2-REQUIREMENT-CONTEXT.yaml` 并发起 CP2 Decision Brief。
3. CP2 通过后，`host-orchestrator` 将 HLD 设计阶段委托给 `meta-se`。用户直接与 `meta-se` 讨论 Architecture Gray Areas 和 advisor table，并使用 `Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch` 表格形成方案输入；随后 `meta-se` 输出含适用性矩阵、Use Case → Architecture Traceability 和场景模拟的 `HLD.md`。用户确认“HLD 草案可提交给 host-orchestrator 发起 CP3”后交还，host-orchestrator 生成 `process/context/CP3-DESIGN-CONTEXT.yaml` 并发起 CP3。
4. `meta-se` 写入 CP4 自动预检；CP4 不再单独人工确认，结果汇入 CP5 批量 LLD 决策摘要。
5. CP3 通过后，`meta-se` 先生成 `docs/design/FEATURE-DESIGN-MATRIX.md`，判定哪些 Feature 需要 `docs/features/<feature>/DESIGN.md` / `TEST-PLAN.md` / `TASKS.md`，并为每个 Story 标记 `feature_design_refs` 与 `lld_policy=full-lld|technical-note|waived`。
6. `meta-dev` 并行输出全部目标 Story 的设计证据和 CP5 自动预检：高风险 Story 输出完整 LLD，`standard-lite` / `allows_batch_lld=true` 下低中风险且共享实现面的 Story 可进入 Batch LLD 并拥有独立 `BATCH-*-LLD.md#story-story-{id}` 证据锚点，低风险 Story 在 Story 卡片中补 `## 技术说明`，明确豁免的 Story 写 waived 证据。遇到实现灰区时只写 `process/state/QUESTION-LEDGER.ndjson` 或 CP5 context queue ref。`host-orchestrator` 作为 question broker 合并问题、批量询问用户、回填答案，然后生成 `process/context/CP5-LLD-CONTEXT.yaml` 和 `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md`，一次性确认全部设计证据、CP4 摘要、clarification 队列、依赖门控和文件所有权。
7. 全量 CP5 确认且 `dev_gate` 满足后，`host-orchestrator` 按 Wave / Story DAG 自动调度 `meta-dev` 并记录证据；交接前生成或更新 `process/context/CP6-IMPLEMENTATION-CONTEXT.yaml`。`meta-dev` 使用 `implementation-execution` 产出实现对象清单、设计契约映射、测试 / Fixture 计划、最小实现切片、平台差异和交接摘要。复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / 护栏 / 平台适配 / 发布相关 Story 写完整 `IMPLEMENTATION.md`，低风险 Story 可写 Story 摘要或 DEV-LOG；实现完成后写入 CP6 编码完成结果。
8. Story CP6 通过后，`host-orchestrator` 自动调度 `meta-qa` 并记录证据；交接前生成或更新 `process/context/CP7-VERIFICATION-CONTEXT.yaml`。`meta-qa` 使用 `verification-execution` 消费 CP6 实现执行证据、设计证据和 `TEST-MATRIX.md` 摘要，输出验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、问题和剩余风险，再用 `quality-review` 固化 TEST-REPORT / REVIEW / FIXES 并写入 CP7。CP7 结论为 `PASS` / `WAIVED` 时进入 verified，`PASS_WITH_RISK` 时可推进但风险进入 CP8，`NEEDS_REWORK` 回 meta-dev，`NEEDS_DESIGN_CLARIFICATION` 回 meta-se / host-orchestrator，`BLOCKED` 阻断。
9. 所有目标 Story 验证后，`host-orchestrator` 自动调度 `meta-doc` 完成文档，`meta-qa` 使用 `release-readiness` 先生成 `process/release/RELEASE-CONTEXT.yaml` 和 `process/context/CP8-DELIVERY-CONTEXT.yaml`，再按 `release_artifact_profile=minimal|compact|full` 裁剪发布文档并写入 CP8 自动预检。CP8 的 `release_decision=READY|READY_WITH_RISK` 才可发起人工终验，`NOT_READY` 阻断，`RELEASED|FAILED` 必须有独立真实发布授权；CP8 Decision Brief 人工终验通过后进入 delivered。

## 检查点

Meta Flow 默认采用 CP0-CP8 检查点。所有检查点都包含 Entry Criteria、Checklist、Exit Criteria、Deliverables。

| CP | 名称 | 类型 | 文件 |
|----|------|------|------|
| CP0 | 原始请求受理门 | 自动 | `process/checks/CP0-REQUEST-INTAKE.md` |
| CP1 | 用户场景完备门 | 自动 | `process/checks/CP1-USE-CASE-COMPLETENESS.md` |
| CP2 | 需求 / 场景 / 范围基线门 | 自动预检 + 人工 | `process/checks/CP2-REQUIREMENTS-BASELINE.md`；`process/checkpoints/CP2-REQUIREMENTS-BASELINE.md` |
| CP3 | 蓝图 / HLD 架构评审门 | 自动预检 + 人工 | `process/checks/CP3-HLD-CONSISTENCY.md`；`process/checkpoints/CP3-HLD-REVIEW.md` |
| CP4 | Story 拆解与并行安全门 | 自动预检（汇入 CP5） | `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md` |
| CP5 | Story 设计证据可实现性门 | 全量自动预检 + 全量人工 | `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md`；`process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` |
| CP6 | Story 编码完成门 | 滚动自动；检查实现执行证据 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md` |
| CP7 | Story 验证完成门 | 滚动自动；检查验证执行证据和结论分级 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md` |
| CP8 | 交付就绪门 | 自动预检 + 人工 | `process/checks/CP8-DELIVERY-READINESS.md`；`process/checkpoints/CP8-DELIVERY-READINESS.md` |

关键人工检查点由 `host-orchestrator` 发起。CP2 / CP3 / CP5 / CP8 发起前会生成 Context Capsule、Decision Brief 和待人工决策清单，并提示 `process/checkpoints/CP*.md` 路径。待人工决策清单的状态机对象是 `process/checkpoints/CP*.md` Decision Brief 与 `process/state/GATE-LEDGER.ndjson`，会逐项列出决策 ID、决策类型、待确认问题、推荐方案、至少 1 个备选方案（优先 2 个）、优劣分析、影响 / 风险和回退 / 切换条件。用户审查后可以在文件的“人工审查结果”中填写结论，也可以在对话中回复 `approve`、`修改: <具体修改点>`、`reject`，由 `host-orchestrator` 回填结果文件；`approve` 表示接受清单内全部推荐方案。CP4 只写自动预检并汇入 CP5。

Codex 平台没有 Claude Code frontmatter `tools: AskUserQuestion` 的同构 agent 字段。Host Orchestrator 在当前 Codex 工具面明确提供 `request_user_input` 时，可用下面的命令把人工门禁转换为结构化提问负载；否则发送命令输出中的 exact-text fallback：

```bash
meta-flow ask-user human-gate --checkpoint process/checkpoints/CP3-HLD-REVIEW.md --format codex-json
meta-flow ask-user human-gate --checkpoint process/checkpoints/CP3-HLD-REVIEW.md --output process/checkpoints/CP3-LAUNCH-MESSAGE.md
meta-flow check human-gate --checkpoint process/checkpoints/CP3-HLD-REVIEW.md --launch-message-file process/checkpoints/CP3-LAUNCH-MESSAGE.md
```

发起人工门禁的对话本身也受校验：必须包含 checklist 路径、自动预检结论、Context Capsule 摘要、决策收集覆盖摘要、待决策项数量、待决策表格或压缩后的 blocking / high-risk 决策摘要和三个 exact 回复。checkpoint 文件中的 Decision Brief 始终完整；对话可按 `decision_brief_profile=full|compact|summary` 压缩。真实运行、凭据、安全、外部接口、数据写入、publish、live / 交易类事项必须独立列为不授权项；`approve` 不代表授权这些操作。CP8 还必须输出 follow-up tracking 分流：关闭范围、不授权范围、风险接受项、后续 CR 候选项、取消 / deferred 项。后续 CR 候选只进入 `process/changes/CR-*-FOLLOW-UP-TRACKING-YYYY-MM-DD.md` 台账，用户决定推进某项时才创建正式 CR。

启动台账中的后续 CR 时，在当前主进程会话中指定台账和候选编号：

```text
启动后续 CR
台账：process/changes/CR-019-FOLLOW-UP-TRACKING-2026-05-31.md
候选编号：CR-020
目标：推进 Windows gateway 实机部署准入
```

host-orchestrator 必须先读取台账、`STATE.current.json.active_change`、`process/changes/CR-INDEX.yaml|json` 与 `process/state/CR-LEDGER.ndjson`、`process/changes/CR-INDEX.yaml`（若存在）和当前活跃 `process/changes/CR-*.md`，执行 CR 冲突预检。`candidate` / `spike_candidate` 只是 backlog，不占执行锁；转为正式 CR 后才把台账状态、`process/changes/CR-INDEX.yaml|json` 与 `process/state/CR-LEDGER.ndjson` 和 `CR-INDEX.yaml` 改为 `active`，写入正式 CR 路径并设置活跃变更。若已有未完成 CR，新 CR 与其影响同一正式文档、Story、文件 owner、外部接口、安全 / 运行授权或风险接受项，默认不得并行推进；host-orchestrator 必须给出合并到现有 CR、保持候选等待、标记 `blocked`、拆分无冲突子集或 `superseded` 的决策表，由用户确认后再继续。

询问“当前状态”或“还有哪些 CR 需要推进”时，host-orchestrator 必须输出 CR 盘点视图：`active formal CR`、`blocked formal CR`、`follow-up candidate`、`spike_candidate`、`stale_status_conflicts`。如果当前项目存在 `meta-flow check cr-tracking`，状态盘点、候选 CR 启动、CR 关闭和 CP8 follow-up 分流后都应运行：

```bash
meta-flow check cr-tracking --project-root .
```

该脚本用于发现 `STATE.current.json.active_change` 指向已关闭 CR、多个 active CR 未授权、follow-up candidate 已有正式 CR 文件、台账 active 项缺正式 CR 路径等问题。

### CR lifecycle 与 impact governance

正式 CR 使用 `process/changes/CR-*.md` 作为完整审计记录，`process/changes/summaries/CR-*.summary.json` 和 `process/changes/CR-INDEX.json` 作为默认机器入口。CR 的状态和关闭证据必须进入 `process/state/CR-LEDGER.ndjson`，检查点结果必须进入 `process/state/CHECKPOINT-LEDGER.ndjson`。关闭或恢复历史 CR 后，运行：

同一 CR 的 CP 不以内联章节作为真相源。CR 文档只维护 `Checkpoint Index`、状态摘要和 ref；自动 CP 真相源是 `process/checks/CP*.result.json`，人工门禁真相源是 `process/checkpoints/CP*.md`，事件真相源是 `CHECKPOINT-LEDGER.ndjson` / `GATE-LEDGER.ndjson`。不得把 CP result、Decision Brief、review 全文或历史 checkpoint 详情复制进 CR 正文；关闭 CR 后只保留 status + ref 指针。

```bash
meta-flow cr summary --id CR-036 --project-root .
meta-flow cr index --project-root .
meta-flow cr check --project-root .
meta-flow cr brief --id CR-036 --project-root .
meta-flow cr brief --id CR-036 --mode enforce --project-root .
```

CR 影响面应优先写结构化字段，而不是只写旧的 `impact_surface`。支持的结构化字段包括：

- `impact_capability_refs`
- `impact_feature_refs`
- `impact_module_paths`
- `impact_policy_refs`
- `impact_process_refs`
- `impact_runtime_refs`
- `impact_data_refs`

旧 `impact_surface` 仍兼容读取。迁移和审计时使用：

```bash
meta-flow cr impact-report --project-root .
meta-flow cr impact-report --mode enforce --project-root .
```

`impact-report` 会合并显式结构化字段与 legacy 推导字段，解析 capability refs，并报告 `uncategorized_legacy`。未分类 legacy 项不得静默丢弃，应进入 follow-up candidate 或人工分类。legacy impact 分类规则默认内置，也可通过 `process/project/IMPACT-SURFACE-RULES.yaml` 配置项目级规则。规则文件属于 process governance artifact；更新后应重新运行 `meta-flow cr impact-report`、`meta-flow cr check` 和相关测试。

CR036 / CR037 的当前治理状态：

- `CR-036`: `closed / READY_WITH_RISK / cp8_recovery_closed`，源码锚点为 `34beb2d Improve approval-oriented CR gates`，剩余风险是原始 CR036 planning / handoff / formal decision artifact 缺失。
- `CR-037`: `closed / READY / cp8_closed`，源码提交为 `c2f5068 Implement CR037 impact surface governance`，覆盖 impact surface split、migration report、uncategorized legacy reporting 和 configurable legacy impact classification rules。

CP2 会额外检查 `process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md` 和 `process/checks/CP2-DISCUSSION-CHECKPOINT.json`，用于追溯 Scenario Gray Areas、用户选择、freeform 确认和 Deferred Ideas。CP3 会额外检查 `process/discussions/CP3-HLD-DISCUSSION-LOG.md` 和 `process/checks/CP3-DISCUSSION-CHECKPOINT.json`，用于追溯 Architecture Gray Areas、advisor table、方案形成输入、核心 ADR 早确认、HLD 后审查意见和切换条件。Discussion Log 用于审计和恢复，不作为默认下游输入；下游先消费 `process/context/*-CONTEXT.yaml`，必要时再读取 `USE-CASES.md`、`REQUIREMENTS.md`、`SCENARIOS.yaml`、`TEST-MATRIX.md`、`STORY-MAP.md`、`MVP-SCOPE.md`、`BLUEPRINT.md`、`DOMAIN-MAP.md`、`DEPENDENCY-MAP.md`、`HLD.md`、`ARCHITECTURE-DECISION.md`、`FEATURE-DESIGN-MATRIX.md` 或 Decision Brief。

异步 power mode（例如 `process/discussions/CP2-QUESTIONS.json/html` 或 `CP3-QUESTIONS.json/html`）是后续可选增强，本轮不作为默认产物或验收前置。

CP6 / CP7 还必须包含 `Agent Dispatch Evidence` 小节。`process/handoffs/*.md` 只表示交接，不表示子 agent 已执行；Story 编码或验证完成必须有 `spawn_agent` / `resume_agent` / `send_input`、平台 Task/Subagent 返回标识，并在 `process/state/AGENT-DISPATCH-LEDGER.ndjson` 或 handoff `dispatch` 中记录 `agent_id` 或 `thread_id`，或用户明确批准的 `inline-fallback`。CP6 必须额外记录实现执行证据路径、证据类型和 N/A 理由；CP7 必须记录验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、问题和剩余风险、阶段决策；缺少调度证据或必需实现 / 验证证据时，CP6 / CP7 只能判定为 `FAIL` 或 `BLOCKED`。

用户启动正式工作流后，同工作流内默认允许 `host-orchestrator` 自动拉起所需功能 Agent。该授权只覆盖真实子 agent 调度；平台无法拉起子 agent 或需要 inline fallback 时，仍必须单独询问用户。

## 阶段委托与 LLD Clarification Queue

`handoff/context delegated_interaction ref or STATE.current.json.active_delegation_ref` 记录当前阶段委托：`phase`、`agent_role`、`agent_id/thread_id`、`handoff_path`、`status`、`started_at`、`returned_at` 和 `return_summary_path`。委托只表示阶段内交互权移交，不表示 CP2 / CP3 已确认。`meta-pm` / `meta-se` 可直接与用户讨论本阶段草案；正式人工门仍由 `host-orchestrator` 发起。

`process/state/QUESTION-LEDGER.ndjson` 或 CP5 context queue ref 记录并行 LLD 阶段的实现灰区。每个 item 至少包含 `id/story_id/owner_agent/question/options/recommendation/pros_cons/impact_surface/blocks_lld/answer/status`，其中 `options` 必须能表达 1 个推荐方案和至少 1 个备选方案。多个 `meta-dev` 不直接并发问用户；`host-orchestrator` 合并同类问题后一次性询问用户，并把答案回填到 queue、独立 LLD 或 Batch LLD Story 锚点、DEV-LOG。存在未回答 `blocks_lld=true` 项时不得发起 CP5；转 OPEN / Spike 的项必须在 CP5 Decision Brief 中暴露。

## fast-lane 快速模式

`fast-lane` 用于低风险轻量实现、小型 Skill / Agent / rules 修订和文档更新。它减少需求 / HLD / LLD / IMPLEMENTATION / VERIFICATION 文档厚度和人工门数量，但不跳过追溯证据。

适用条件：

- 不改变架构、安装路径、权限边界、安全规则或外部接口契约
- 不涉及多个 Story、文件所有权冲突、运行时依赖或不可逆迁移
- 可以用一页 `Intent + Approach Brief` 解释范围、做法、验证和风险

不适用时自动升级 `standard`。fast-lane 仍必须保留 `REQUEST.md`、`STATE.md`、必要变更记录、CP6 / CP7、Agent Dispatch Evidence、实现执行证据摘要、验证执行证据摘要、`process/release/RELEASE-CONTEXT.yaml` 和 CP8 终验摘要；发布阶段默认使用 `release_artifact_profile=minimal`，不生成完整 release 长文档，除非用户明确要求或触发安装 / 权限 / 迁移 / 外部接口风险。

CP2 / CP3 的讨论增强不会强行把所有小修改升级为 standard；只有出现架构、权限、安全、平台安装、外部接口、文件所有权冲突或多 Story 依赖等条件时才升级。fast-lane 下若 discussion log / checkpoint 不适用，自动检查必须写明 N/A 原因。

## 交付目录约定

安装脚本从 `delivery/` 内读取交付件，推荐使用 `meta-flow install`：

```bash
# user scope 默认只安装 rules
meta-flow install codex --scope user

# project scope 默认安装 full 组件（rules + agents + skills）
meta-flow install codex --scope project --project-dir /path/to/project

# 未指定 --project-dir 时，交互式终端会提示确认当前目录或输入其他目录
meta-flow install codex --scope project

# 显式安装完整组件
meta-flow install codex --scope project --component full --project-dir /path/to/project

# Qoder 安装（project scope 共享 AGENTS.md，使用 platform-tagged managed block 隔离）
meta-flow install qoder --scope project --project-dir /path/to/project

# 卸载安装记录中的组件，默认卸载 full
meta-flow uninstall codex --scope project --project-dir /path/to/project
meta-flow uninstall codex --scope project --component rules --project-dir /path/to/project
```

非交互环境的三平台项目级 dry-run 必须显式提供 `--project-dir`：

```bash
uv run --python 3.11 meta-flow install codex --scope project --component full --project-dir . --dry-run
uv run --python 3.11 meta-flow install claude --scope project --component full --project-dir . --dry-run
uv run --python 3.11 meta-flow install qoder --scope project --component full --project-dir . --dry-run
```

兼容运行方式：

```bash
# 从项目根目录运行
uv run --python 3.11 python delivery/scripts/install.py claude

# 以 delivery/ 为根（独立 Git 仓库）运行
cd delivery
uv run --python 3.11 python scripts/install.py claude
```

交付目录结构：
- `delivery/agents/` — canonical Agent 定义
- `delivery/skills/` — canonical Skill 定义（含 `<skill>/templates/`、`<skill>/scripts/` 等私有运行时资产）
- `delivery/rules/` — 平台规则文件
- `delivery/doc/PLATFORM-CONTRACTS.yaml` — 平台安装路径单一真相源，安装器、DryRun 与 guardrail 共同读取

组件语义：

- `rules`：只安装平台规则入口（AGENTS.md 为唯一源；claude 平台生成 CLAUDE.md）
- `agent`：安装 agents + skills
- `full`：同时安装 rules 与 agent 组件
- `meta-flow uninstall <platform>` 未指定 `--component` 时默认卸载 `full`；可用 `--component rules|agent|full` 精确卸载组件
- legacy `--content all|agents|skills|rules` 仅保留兼容，新文档优先使用 `--component`

Agent 命令与显示区分：

| canonical role | Codex 命令 / nickname_candidates | Codex 模型 | Codex `model_reasoning_effort` | Claude Code color |
|---|---|---|---|---|
| `meta-pm` | `pm-wu`、`pm-zheng`、`pm-wang`、`pm-feng`、`pm-chen` | `gpt-5.6-terra` | `medium` | `orange` |
| `meta-se` | `se-chu`、`se-wei`、`se-jiang`、`se-shen`、`se-han` | `gpt-5.6-terra` | `high` | `yellow` |
| `meta-dev` | `dev-yang`、`dev-zhu`、`dev-qin`、`dev-you`、`dev-xu`、`dev-he`、`dev-lv`、`dev-shi`、`dev-zhang`、`dev-kong` | `gpt-5.6-terra` | `medium` | `green` |
| `meta-qa` | `qa-he`、`qa-lv`、`qa-shi`、`qa-zhang`、`qa-kong`、`qa-cao`、`qa-yan`、`qa-hua`、`qa-jin`、`qa-wei` | `gpt-5.6-terra` | `high` | `cyan` |
| `meta-doc` | `doc-cao`、`doc-yan`、`doc-hua`、`doc-jin`、`doc-wei` | `gpt-5.6-luna` | `low` | `purple` |

canonical role 名称仅用于功能子 agent 的状态机、handoff 和检查点审计；Host Orchestrator 是当前会话主进程职责，不安装平台 agent 文件。Codex 安装器把上表命令、模型和推理等级写入 `.codex/agents/*.toml`。模型路由由安装器的 Codex-only 映射提供，不写入跨平台 canonical Agent front matter；Claude Code 文件型 subagent 不支持 nickname，安装器使用 `color` 字段在任务列表和 transcript 中区分角色。主进程建议父会话在标准 / 复杂工作流中使用 `model_reasoning_effort="high"`，fast-lane 或小范围机械修改可使用 `medium`。

Codex 还会安装动态思考 profile，但 canonical role 不变：`meta-dev-debugger`、`meta-se-critical` 与 `meta-qa-critical` 都使用 `gpt-5.6-sol`，对应推理等级分别为 `high`、`xhigh`、`xhigh`。Host Orchestrator 调度时必须在 `AGENT-DISPATCH-LEDGER.ndjson` 或 handoff `dispatch` 记录 `canonical_role`、`codex_agent_name`、`reasoning_profile` 和 `dispatch_trigger`。

Qoder 复用 canonical Agent 定义和 reasoning profile，但不复用 Codex-only 的 GPT-5.6 模型覆盖；输出为 `.qoder/agents/*.md`（Markdown + YAML frontmatter）。Qoder 不使用 `nickname_candidates`，改用 `effort` 字段映射 `model_reasoning_effort`（`minimal` → `low`），并复用 Claude Code 的 `color` 字段。

Codex 主进程启动正式工作流后默认授权真实子 agent 调度；若当前工具面有 `spawn_agent` / `resume_agent` / `send_input`，创建 `mode=subagent` handoff 后必须调用对应工具。只创建 handoff 不能算子 agent 已执行；工具不可用时必须阻断并记录 `subagent_dispatch.available=false`，除非用户明确批准 `inline-fallback`。

## 交付护栏

1. `delivery/scripts/` **只允许**安装器入口：`install.py`、`install.sh`、`install.ps1`。
2. 任何被 active Skill 运行时使用的模板、脚本、schema、示例，都必须放在 `delivery/skills/<skill>/` 私有子目录下。
3. active Skill 的 `SKILL.md` 不得引用 `delivery/scripts/*.py`，也不得使用依赖当前工作目录的 `python scripts/...` 写法。
4. Python 缓存/编译产物（`__pycache__/`、`*.pyc`）不得入库。
5. Codex Skill 禁止安装到 `.codex/skills` 或 `~/.codex/skills`；项目级使用 `.agents/skills`，用户级使用 `~/.agents/skills`。
6. 安装器必须在写入前检查路径组件冲突；例如目标 `.codex` 已是普通文件时，应明确报错 `安装路径被非目录占用`，不得输出 Python traceback。

meta-flow 自身仓库级静态检查命令：

```bash
uv run --python 3.11 python scripts/check_delivery_guardrails.py
```

发布前 preflight 使用以下五门固定入口；每门的原始退出码、warning 和风险都必须保留，不能把 `OK_WITH_WARNINGS` 改写成全绿：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run --python 3.11 pytest -q
uv run --python 3.11 ruff check .
PYTHONDONTWRITEBYTECODE=1 uv run --python 3.11 python scripts/check_delivery_guardrails.py
PYTHONDONTWRITEBYTECODE=1 uv run --python 3.11 meta-flow doctor all --project-root .
PYTHONDONTWRITEBYTECODE=1 uv run --python 3.11 meta-flow check cr-tracking --project-root .
```

该脚本不属于外部 production 项目的默认交付物。仅当当前仓库存在 `scripts/check_delivery_guardrails.py` 时才运行上述命令。若在其他项目使用 meta-flow 生成或安装工作流，而目标项目没有该脚本，外部 production 项目不得硬引用 `<project-root>/scripts/check_delivery_guardrails.py` 或任意设备绝对路径；应按目标项目 README/docs 中的测试、构建、安装 dry-run 或用户确认的验证命令执行。

命名规则：

- Claude Code / OpenClaw 的 Agent 文件后缀保持为 `.md`
- Codex 目标会自动转换为 `.toml`

## 快速使用 meta-flow

首次启动一个正式交付工作流时，建议直接给出目标、平台和约束：

```text
开始
目标：为 <agent / skill / workflow 名称> 产出正式方案
平台：Claude Code、Codex、Qoder
要求：先澄清需求，再给我 HLD，确认后再拆 Story
```

常用控制语句：

```text
当前状态
下一步
继续
快速修改
```

CLI 也提供只读辅助入口：

```bash
meta-flow status
meta-flow next
meta-flow doctor
meta-flow doctor tokens --project-root .
meta-flow state check --project-root .
meta-flow cr check --project-root .
meta-flow context build --stage CP6 --profile standard-code --cr CR-101 --project-root .
meta-flow context check --context process/context/CP6-CR101.context.json --project-root .
meta-flow context build-story-packet --story process/stories/STORY-CR123-S01.md --stage CP6 --project-root .
meta-flow context check-story-packet --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --project-root .
meta-flow cp result-check --result process/checks/CP6-STORY-CR123-S01.result.json --project-root .
meta-flow cp render-summary --result process/checks/CP6-STORY-CR123-S01.result.json
meta-flow cp ledger-append --result process/checks/CP6-STORY-CR123-S01.result.json --project-root .
meta-flow event check --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint
meta-flow story return-check --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .
meta-flow story evidence-index --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .
meta-flow story verify-packet --from-return process/returns/STORY-CR123-S01.CP6.return.json --story process/stories/STORY-CR123-S01.md --project-root .
meta-flow design delta-check --delta process/design-deltas/STORY-CR123-S01.delta.json --project-root .
meta-flow design delta-check --delta process/design-deltas/STORY-CR123-S01.delta.json --require-merged --project-root .
meta-flow feature check --project-root .
meta-flow feature trace --project-root .
meta-flow check imports --project-root .
meta-flow check risk-rings --changed-files quant_lab/trading/order.py --project-root .
meta-flow check capability-claims --artifact README.md --project-root .
meta-flow check concept-overlap --changed-files quant_lab/engine/contracts.py --project-root .
meta-flow check package-identity --project-root .
meta-flow gate classify --changed-files README.md
meta-flow governance truth-map-check --project-root .
meta-flow governance retention-check --project-root .
meta-flow policy list --project-root .
```

如果当前是在优化 meta-flow 本身，而不是为目标产物交付方案，请显式声明：

```text
当前是在做 meta 工作流优化，请进入 meta-self-dev 模式。
```

详细使用说明见 [delivery/README.md](delivery/README.md) 和 [delivery/doc/USER-MANUAL.md](delivery/doc/USER-MANUAL.md)。
