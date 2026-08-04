# Meta Flow 交付规则（Slim Canonical Source）

## 0. 权威边界

本文件是交付包的简明执行入口；细节只以 `delivery/rules/AGENT-SKILL-CONTRACT.md`、`delivery/rules/DIRECTORY-CONTRACT.md` 与各 Skill 的 `SKILL.md` 为准。Agent / Skill Contract Slimming 只能去重，不得降低安全、授权、状态机、过程仓解析或平台路径语义。

`process/...` 是逻辑引用。首次 I/O 前必须执行 `meta-flow project resolve-ref --project-root <release-root> --logical-ref <process/...> --format json`；只瞬时使用 `resolved_path`，退出码 2 即 BLOCKED。不得猜测 sibling、去掉前缀、恢复软链接或回退 legacy。

vNext 默认 `route_mode=sibling-binding`；`relative-symlink` 仅是显式 legacy Agent/Skill 兼容模式。不得声称 binding-only 已兼容全部 legacy Skill。`.meta-flow/workspace.yaml` 是 tracked 真相；`.meta-flow/INSTALL-MANIFEST.yaml` 必须忽略。

## 0.1 长期治理查询与阶段规划

- 用户询问“阶段目标、长期路线、Roadmap、下一阶段、后续规划或阶段重叠”时，必须按 `process/PROJECT.yaml → roadmap_ref → process/ROADMAP.yaml → 全部 declared phase_refs` 查询；不得只看当前 Work、最近对话或 memory。
- 默认 5 对象限制保留；长期路线允许 `PROJECT + ROADMAP + 全部 declared phase_refs` 的有界例外。active Phase 详细路线只按其 `result_refs` 读取声明的实施计划；禁止 sibling discovery、目录猜测和全历史扩读。
- 回答固定区分“机器事实 / 解释或推断 / 建议”。memory 仅作线索，仓库真相优先。
- 提议新 Phase 前必须输出目标、进入/退出条件、非目标和生命周期结果的重叠矩阵；可归入现有 active/planned Phase 时使用 Work/工作流，不新建 Phase。

## 1. 先验检查（任何危险动作前）

1. 调 API 前，使用签名、类型注解、正式 schema 或 canonical contract 确认返回类型；Python `_resolve_runtime_ref` / `_resolve_runtime_path` 返回 `pathlib.Path`，只有 CLI `meta-flow project resolve-ref --format json` 返回含 `resolved_path` 的 JSON。
2. 读文件、解析或 target I/O 前先确认目标存在；不可用“预期存在”代替检查。
3. 改文件前先读取当前原文或 native 结构化对象，并只按该快照构造补丁；失败时保持原 bytes，不写部分替换。
4. 写治理状态前先读取 owner 的合法枚举与 transition graph。禁止手工改派生状态：`lifecycle_status`、`readiness_status`、`gate_status` 以及 CR summary/index/ledger/checkpoint projection 必须由 native lifecycle/status-sync 推导。

## 2. 授权、风险与 Git

- 不读取凭据、不执行生产写、网络、真实安装、发布、外部项目操作或 legacy 操作，除非有独立 typed authorization；设计或 `approve` 不等于运行授权。
- `git commit`、push、merge、tag、release、新 remote 与凭据/权限变更均不授权。Git index 八分类后，只有 tracked regular/prospective untracked 可 mutation；symlink/missing/ignored 只验证，submodule/outside/duplicate 阻断；禁止 `git add -f`。
- 正式 CR 使用 native formal truth；`CR-INDEX.json` 是可删除重建投影。状态变更走 `meta-flow cr status-sync` 的 plan/apply/recovery，异常先 inspect；`PARTIAL`/`RECOVERED` 不可继续。Decision Bundle 只冻结同一 revision 的确认；任一子门失败/阻断即停止。
- 高风险未知事实必须 BLOCKED，不得静默降级。失败结论只使用 `PASS`、`PASS_WITH_RISK`、`BLOCKED`、`NEEDS_REWORK`、`NEEDS_DESIGN_CLARIFICATION`、`WAIVED`；`CHECK_HARNESS_ERROR` 单独标记，不能伪装真实内容失败。

## 3. Work、上下文与门禁

- 默认建立 Work；公共契约、架构/安全边界、不可逆迁移、生产写、正式发布、强审计、风险接受或跨阶段重构才建 CR。G0/G1 不投射 legacy CP0-CP8；G2 按批准预算执行。
- deny-default scope 控制 reads/writes/checks；优先消费 Context Capsule：`process/context/` 的 work packet、`allowed_reads` 与 `must_read`。`process/STATE.md`、完整 CR、无关 Story、完整 LLD 与历史 transcript 默认不读；展开读取必须有 `full_doc_read_reason` 和 read expansion 证据。
- 全阶段 Context Capsule、上下文预算、Workflow Health、Decision Brief 压缩均由原生上下文与检查模块维护。人工门由 Host Orchestrator 发起，使用 `process/checkpoints/`；用户回复 `approve` 只接受列明推荐方案，不授权禁止动作。
- 产品输入在 `docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md`、`docs/product/MVP-SCOPE.md`；设计边界在 `docs/design/BLUEPRINT.md`、`docs/design/DOMAIN-MAP.md`、`docs/design/FEATURE-DESIGN-MATRIX.md`。不得以讨论稿、猜测或摘要替代它们。

### 3.1 普通 Work 的四阶段与防重做契约

- 新建或缺少路由声明的 Work 使用安全默认：`mode=routine-four-stage`、`dispatch_mode=direct`、`legacy_cp_compatibility=false`、`validation_profile=layered-v1`、`failure_scope=current-slice-only`。普通路线只有“澄清目标 → 计划切片 → 直接实施 → 分层验证”四阶段；G0/G1 不调度功能 Agent，也不创建 CP、status-sync 或 handoff 自治理产物。
- legacy CP0-CP8 只能由当前 `WORK.yaml.route_profile.legacy_cp_compatibility=true` 显式进入，并同时满足 G2、人工批准、legacy gate evidence 和对应 scope；Skill、Agent、模板、环境变量或旧文件均不能隐式开启。
- 验证顺序固定为 targeted → compatibility → full。PASS receipt 必须绑定 source/profile fingerprint、check layer、command identity、环境摘要和 result digest；fingerprint 不变才可复用。FAIL、命令漂移或 partial mutation 不得复用，失败只回当前切片和已失效层，不能重跑无关 Story。
- 默认查询由单 operation、显式注入的读取上下文执行，最多读取 5 个对象；第 6 个对象、scope 外 ref、未声明 long-term Phase 或 stale context 必须在读取正文前阻断。plan 与 apply 不得共享 context；apply 必须重新验证授权、scope、OID、dirty-path 和 target preimage，mutation 后旧 context 不再可读。
- 全文扩读只接受 `capsule_missing`、`field_conflict`、`schema_validation_failed`、`human_audit`、`summary_insufficient` 五类 reason 及其机器证据；`deep_review` 仅兼容读取历史事件，不能创建新请求。
- CURRENT、summary、evidence 与 WORKFLOW-HEALTH 的 writer 必须按语义比较：只有 `updated_at` / `created_at` 或零增量变化时 actual mutation 为 0；append-only ledger、truth preimage 和 transaction recovery 边界不因 no-op 优化而放宽。

## 4. Story 设计与实现

- CP4、全部目标 Story 的设计证据与 CP5 人工确认通过前不得实现。Story 必须消费 `lld_policy`、已确认 LLD/technical-note/waived、依赖门控与 file ownership；冲突或缺 AI 任务清单即 BLOCKED。
- full-lld 保持 14 个可见章节；batch-lld 必有独立 `BATCH-*-LLD.md#story-story-{id}` 锚点，高风险不得降级。并行 LLD 问题写 queue，由 Host Orchestrator 批量处理。
- 实现前调用 `implementation-execution`：记录实现对象清单、设计契约映射、测试 / Fixture 计划、最小实现切片、平台差异、验证结果和 handoff。复杂、Prompt/Skill/Workflow、安装器、Guardrail、平台适配或高风险 Story 必写 `IMPLEMENTATION`。
- CP6 后以 Return Packet 与 Evidence Index 为机器证据；CP7 用 `verification-execution` 输出 `VERIFICATION-REPORT`、追踪矩阵和分层验证。质量评审消费 CP6；`PASS_WITH_RISK` 必须进入后续决策。

## 5. 平台、安装与交付

- `delivery/doc/PLATFORM-CONTRACTS.yaml` 是平台路径唯一事实源；不得按目录类比。Codex Agent 位于 `.codex/agents`，Skill 位于 `.agents/skills`，不得写 `.codex/skills`。
- 安装前逐级检查父路径；非目录占用必须 fail fast，不能暴露 traceback。`meta-flow install <platform>` / `uninstall <platform>` 为入口；禁止真实安装，除非独立授权。
- active Skill 的 templates/scripts/schemas/examples 与 Skill 同树；交付脚本只放安装器入口。Python 使用 `uv`；不提交 `__pycache__/` 或 `*.pyc`。

## 6. 路由与停止

Host Orchestrator 维护调度证据与阶段状态。meta-dev 默认不直接问用户；澄清交给 host。任何输入缺失、契约冲突、越权、错误模型不明、文件所有权冲突或真实检查失败，写最小阻塞证据并停止当前 Story；不得转做其他 TASK-ID。

复用 canonical 文档不等于弱化：本文件保留所有必须先验、禁止和停止条件；下游需要详细字段、模板、枚举或命令时必须打开其权威 source。

## 7. 兼容执行索引（权威细节见引用合同）

- Codex 人工门仅在能力存在时调用 `request_user_input`；展示 `approve`、`修改: <具体修改点>`、`reject`，历史别名只兼容。待人工决策须列决策类型、备选方案、优劣和不授权项；无结构化能力时由 Host 以 exact text 转发。
- 交付路由先识别 production 项目的 README / docs / 交付约定；不得把本仓默认路径强加给目标项目。vNext binding-only 适用于 G0/G1/G2；legacy 扩展仅在人工门显式选择后适用。
- Agent Dispatch Evidence 必含 `agent_id`、`thread_id`、`tool_name`、`completed_at`、`codex_agent_name`、`reasoning_profile`、`dispatch_trigger`；真实调度用 `spawn_agent`、`resume_agent` 或 `send_input`。`inline-fallback` 需用户明示批准，不能伪装子 agent 已执行；未启动为 `spawn-requested`。
- Human Gate Launch Protocol 记录 `GATE-LEDGER.ndjson`、不授权项与 FOLLOW-UP；启动后续 CR 前做 CR 冲突预检。CR 跟踪状态查询消费 `CR-LEDGER.ndjson`、`CR-INDEX.json`，列出 `stale_status_conflicts`。
- CR first 不等于跳过产品澄清：大块集中需求入口分流给 meta-pm，经 CP2 后以目标包或正式 CR 继续；不得直接实施。
- 软件工作流的 release 证据使用 `docs/release/DEPLOY-CHECKLIST.md`、`process/release/RELEASE-CONTEXT.yaml`、`workflow_health`、`decision_brief_profile`、`release_artifact_profile` 与 `release_decision`。
- Agent / Skill Contract 的当前入口是 `process/state/STATE.current.json` 与 `process/current/CURRENT.json`；CR Checkpoint Index 只作导航。治理执行闭环补充（CR-058）：按 `1 / 2 / 2` 预算、targeted revalidation、`PASS_WITH_BASELINE_LIMITATION` 与 formal-only index 执行；不授权 `git commit`。
