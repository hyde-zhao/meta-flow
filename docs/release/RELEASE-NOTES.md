---
project_id: "meta-flow"
release_scope: "meta-flow-context-budgeted-governance"
release_decision: "READY_WITH_RISK"
created_at: "2026-06-17T13:49:25+08:00"
---

# Release Notes

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-11 | host-orchestrator | 新增 workflow eval governance 发布说明 |
| 1.1 | 2026-06-17 | host-orchestrator | 扩展至 process/docs artifact routing、workspace health 和 advanced eval runner |
| 1.2 | 2026-06-21 | host-orchestrator | 增加 context-budgeted governance、架构治理、Story packet、CP result/event ledger 和端到端回归 fixture 收敛说明 |
| 1.3 | 2026-06-21 | host-orchestrator | 增加 Governance Truth Map / Retention Policy、profile-driven Feature taxonomy、CR type 和 Concept conflict key aliases |
| 1.4 | 2026-06-21 | host-orchestrator | 增加 Context Sufficiency、Read Expansion Ledger、Context Doctor 和输出预算治理 |
| 1.5 | 2026-06-21 | host-orchestrator | 增加 Failure Routing / Waiver Governance、不可豁免项和风险接受状态约束 |
| 1.6 | 2026-06-21 | host-orchestrator | 增加 Quality Model / Eval Matrix、quality init、quality / workflow doctor 和 delivery 模板路由 |
| 1.7 | 2026-06-21 | host-orchestrator | CR-034 增加目标项目 adoption readiness、workspace bootstrap、identity scan、adoption doctor 和 bootstrap CR / CP0 context 链路 |
| 1.8 | 2026-06-29 | host-orchestrator | 新增 Qoder 平台安装支持、platform-tagged managed block 机制和 agent effort/color 映射 |
| 1.9 | 2026-07-03 | host-orchestrator | CR-036 recovery closure 与 CR-037 impact surface governance 收束；新增结构化影响面、migration report、uncategorized legacy 和 configurable legacy classification rules |
| 1.10 | 2026-07-04 | host-orchestrator | CR-038..CR-044 收束 CR155 复盘 follow-up：CP0/CP7 硬门禁、CP8 fact diff、release docs 压缩、governance dependency warning、checker provenance、publication authz、CP1 分级、archive 隔离、real-lake validation wrapper 和 Story 管理真相源合并 |
| 1.11 | 2026-07-11 | meta-doc | CR-045 增加 CR-aware route plan、N/A / WAIVED 语义与 route-driven state transition；记录 CP2 / CP5 事后恢复审批和 CP7 四项 HIGH finding 闭环 |
| 1.12 | 2026-07-11 | host-orchestrator | CR-045 更新至最终 R6 证据（9/9、17/113/329），精确标注 `next_action.stop_reason`，披露 dispatch receipt 限制，并记录后续 commit/push 授权 |
| 1.13 | 2026-07-15 | host-orchestrator-inline/meta-qa | CR-047 收敛 workflow truth、portable routing、Doctor/guardrail/Ruff/installer preflight 与 CR-046 protected-object firewall；CP8 候选为 `READY_WITH_RISK`。 |
| 1.14-candidate | 2026-07-19 | host-orchestrator | CR-052 vNext 本地实现候选：每项目独立发布库/过程库、弹性 Project/Phase/Work、G0/G1/G2、scope/budget、snapshot-only adoption、单仓 publication、六维复盘和有界自进化；用户已单独授权把当前两仓整改成果普通 commit/push 到各自远端分支，真实迁移、tag、production/runtime 发布仍未授权。 |
| 1.15-candidate | 2026-07-23 | host-orchestrator | CR-057 Linux 项目接入能力成熟候选：统一 12 字段计划、双仓 6 个 exact OID 检查点、snapshot seed、typed authorization、partial/recovery 和隔离 F1/F2；CP8 自动预检为 `READY_WITH_RISK`，等待人工终验。 |

## 发布范围

| 范围 | 内容 | 证据 |
|---|---|---|
| Workflow eval governance | `meta-flow eval validate/run/suite-health`、eval contracts、fixture、suite health、optional adapter policy | CR-018..CR-023 |
| Process artifact routing | `process/` 外置到 `<artifact-root>/process/meta-flow`，其中 `artifact_root` 以相对项目根记录，例如 `../meta-flow-artifacts` | CR-024、CR-026 |
| Docs artifact routing | 内部 docs 外置到 `<artifact-root>/docs/meta-flow`，其中 `artifact_root` 以相对项目根记录，例如 `../meta-flow-artifacts` | CR-027、CR-030 |
| Eval runner hardening | 新增 grader、case results 和 expected failure 语义，新增 advanced fixture | CR-028 |
| Context-budgeted governance | `STATE.current.json`、CR ledger/summary、context pack/read policy、gate/authz policy、Feature/Module/Capability/Package/Concept governance、Story Context Contract、Story Return/Evidence/Design Delta、CP Result/Event Ledger | MF-001..MF-013 |
| End-to-end regression fixture | `evals/fixtures/context-budgeted-meta-flow/` 与 `tests/test_context_budgeted_flow_e2e.py` 覆盖默认上下文最小化链路 | MF-013 |
| Governance lifecycle policy | `process/policies/SOURCE-OF-TRUTH-MAP.yaml`、`process/policies/RETENTION-POLICY.json`、`meta-flow governance *`、Feature taxonomy policy、CR `cr_type`、Concept `conflict_keys` | MF-015 |
| Context sufficiency / read expansion governance | `meta-flow context sufficiency-check`、`meta-flow context read-log/read-log-check`、`meta-flow doctor context`、`process/state/READ-EXPANSION-LEDGER.ndjson`、output profile budgets | MF-016 |
| Failure routing / waiver governance | `process/policies/FAILURE-ROUTING.json`、`process/policies/WAIVER-POLICY.json`、`meta-flow failure *`、`meta-flow waiver *`、CP result route / waiver 联动校验 | MF-017 |
| Quality / eval governance | `process/policies/QUALITY-MODEL.yaml`、`process/policies/EVAL-MATRIX.yaml`、`meta-flow quality init/model-check/eval-check`、`meta-flow doctor quality/workflow`、delivery quality/eval templates | MF-018 |
| Target project adoption readiness | `meta-flow workspace bootstrap`、`meta-flow identity scan`、`meta-flow doctor adoption`、`meta-flow cr bootstrap`、CP0 result/summary/context、CR-xxx bootstrap naming | CR-034 |
| Qoder 平台安装支持 | `meta-flow install qoder`、platform-tagged managed block、`render_qoder_agent`、effort/color 映射、guardrail 检查 | — |
| CR impact surface governance | `meta-flow cr impact-report`、结构化 `impact_*` split fields、capability resolver-backed report、`uncategorized_legacy`、follow-up candidate、`process/project/IMPACT-SURFACE-RULES.yaml` legacy 分类规则 | CR-037 |
| Historical CR recovery | CR036 recovery stub、CP0 recovery verification、CP8 recovery closure、CR ledger / checkpoint ledger recovery events | CR-036 |
| CR155 follow-up hard gates | scope/authz L1/L2/L3 consistency check、CP2 `required_evidence` schema、CP7 promise-evidence alignment、missing vs negative evidence taxonomy、capsule zone/dedup check、standard-lite + batch LLD support | CR-038 |
| CP8 and release compression | CP8 `fact_diff`、result-first derived consistency、release context first、minimal/compact/full release artifact profiles、DEFERRED_FOLLOW_UP risk handling | CR-039 |
| Audit and efficiency follow-ups | governance dependency warning、checker provenance、repository publication authz、CP1 graded result、archive/backups isolation、`meta-flow validation run` real-lake-readonly task wrapper、`meta-flow story plan-check` 和 DEVELOPMENT-PLAN Story truth source | CR-040..CR-044 |
| CR-aware workflow routing | 按 CR type / traits / gate profile 生成 checkpoint route；显式区分 N/A 与 WAIVED；审批或自动 CP 后按 route plan 推进至下一人工门或明确 stop reason | CR-045；`process/release/RELEASE-CONTEXT-CR045.yaml` |
| Workflow truth and delivery governance remediation | State v2/CR JSON/CURRENT 关系校验、CR-033 candidate retention、路由幂等、Doctor 历史分类、clean-clone/cache guardrail、Ruff 0、三平台非交互 dry-run、CR-046 object-identity firewall | CR-047；`process/release/RELEASE-CONTEXT-CR047.yaml` |

## 用户可见变化

- 新增 vNext 默认路径：`meta-flow project init/check/status/query`、`meta-flow work classify/init/status/review-plan/validation-plan/handoff/resume-check`、`meta-flow repository commit/push`、`meta-flow retrospective *` 与 `meta-flow evolution *`。新项目使用 sibling 独立过程库，不再默认使用 shared artifact worktree、双 leg 或 aggregate。
- G0/G1 固定资源上限并强制 deny-default Work scope；G2 必须显式预算。复盘固定六维并区分事实/推断/人工判断与 measured/proxy/unavailable；复盘、建议批准、实现启动和 publication 授权严格分离。
- 旧 `workspace bootstrap/push`、project integration、dual-leg 与 `cr aggregate` 保留为 legacy 能力；本候选未执行当前 meta-flow 真实路由切换、远端操作或任何破坏性 Git。
- 新增 `meta-flow workspace check/link`，用于检查或建立外置 process 工作区。
- `meta-flow status`、`meta-flow next`、`meta-flow doctor` 和 CR tracking 会先检查 process symlink health；断链或项目不匹配时阻断恢复。
- 源码仓库不再跟踪 `process/` 和 `docs/` 普通过程目录；过程文件由 `meta-flow-artifacts` 仓库跟踪。
- 新增 `meta-flow eval validate/run/suite-health` 本地评估命令和 workflow eval fixtures。
- eval runner 新增 gate、state machine、table schema、artifact trace、expected failure 等 deterministic grader。
- 新增轻量运行态、CR 生命周期、context pack、Story packet、Story return、evidence index、CP result 和 event ledger 命令，默认上下文不再读取 `process/STATE.md`、`process/DEVELOPMENT-PLAN.yaml`、完整 CR 或全量 Story LLD。
- 新增 Feature Registry、Module Boundary、Risk Ring、Capability Status、Package Identity 和 Concept Owners 检查，用于防止长期设计和模块边界在后续项目中漂移。
- 新增 Agent / Skill Contract，要求功能 Agent 默认只消费 context pack / Story packet 的 `allowed_reads`，全文读取必须记录允许枚举内的 `full_doc_read_reason`。
- 新增 context-budgeted 端到端 fixture，验证 `STATE.current.json -> CR summary -> context pack -> Story packet -> Story return -> evidence index -> CP result -> checkpoint ledger` 链路。
- 新增 `meta-flow governance init/truth-map-check/truth-map-render/retention-check/check`，将机器真相源策略放入 `process/policies/SOURCE-OF-TRUTH-MAP.yaml`，并将人类说明渲染到 `docs/design/SOURCE-OF-TRUTH-MAP.md`。
- Feature Registry 支持 `product_domain`、`capability` 和 `design_doc_policy`；`architecture-major`、`product-redesign`、`runtime-high-risk` 等 profile 必须声明产品域和能力层级。
- CR lifecycle 支持 `cr_type`，并兼容旧 `cr_kind`；Concept Owners 支持 `conflict_keys`，不新增独立 conflict key registry。
- Story packet 新增上下文足够性检查，防止 token 压缩过度导致缺少 Feature context、CR delta、dependency inputs、读写边界、验收和验证计划。
- 全文读取审计迁移到 `process/state/READ-EXPANSION-LEDGER.ndjson`；`context read-log` 负责写入事件，`doctor context` 用高频展开读取反推 Feature summary / Story packet 摘要质量缺口。
- Artifact budgets 增加 `output_profiles`，约束 Story return summary、CP summary、compact Decision Brief 和 Feature design summary 的输出字数。
- CP result 的高严重度失败必须有动作式 `route_on_fail`；waiver 必须声明 scope、expiry、approval_ref 和 forces_release_status。
- 未授权 runtime、credential / secret、missing dispatch evidence、runtime-high-risk forbidden path、missing read expansion log、missing evidence 和 false runtime-ready capability claim 不可被 waiver 绕过。
- 新增 `meta-flow quality init --project-root .`，为新项目初始化 `QUALITY-MODEL.yaml` 和 `EVAL-MATRIX.yaml`。
- 新增 `meta-flow quality model-check`、`meta-flow quality eval-check`、`meta-flow doctor quality` 和 `meta-flow doctor workflow`。
- Quality / eval 模板随 `context-manifest-builder` skill 安装；workflow metrics 只从 CP result、event ledger 和 read-expansion ledger 派生，不新增手工 `WORKFLOW-METRICS` 真相源。
- 新增 `meta-flow workspace bootstrap --artifact-root <relative-artifact-root> --project-name <project-name> --project-root .`，一条命令建立 process symlink、route metadata、`STATE.current.json`、`STATE.md` 摘要和基础 ledgers。
- 新增 `meta-flow identity scan --project-root .`，只读报告 package identity 和 README/docs delivery routing 建议，不自动写 production 项目路由。
- 新增 `meta-flow doctor adoption --project-root .`，聚合 workspace、state、CR tracking、identity、quality、workflow ledger 和 human gate readiness；该命令不读取凭据、不执行 runtime、不写业务文件。
- 新增 `meta-flow cr bootstrap --id CR-001 ...`，创建 active bootstrap CR、CR summary/index/ledger、CP0 result/summary 和 CP0 context。正式新编号统一 `CR-xxx`，`MF-xxx` 仅作为历史别名。
- 新增 Qoder 平台安装支持：`meta-flow install qoder` / `meta-flow uninstall qoder`，project scope 安装到 `.qoder/agents/*.md` 和 `.qoder/skills/`，user scope 安装到 `~/.qoder/`。
- 新增 platform-tagged managed block 机制：Qoder 与 Codex 在 project scope 共享 `AGENTS.md` 时，使用 `<!-- myflow:managed:begin platform=qoder -->` 标签隔离各平台内容；卸载一个平台不影响另一个平台的已安装内容。旧的无标签 managed block 自动迁移。
- Qoder agent 复用 Codex agent 定义和 reasoning profile，输出为 Markdown + YAML frontmatter；`effort` 字段映射 `model_reasoning_effort`（`minimal` → `low`），`color` 字段复用 Claude Code 调色板。
- Guardrail 检查扩展：`collect_platform_contract_errors` 增加 Qoder 路径断言，`collect_agent_display_profile_errors` 增加 Qoder effort/color 验证，`collect_installer_component_errors` 增加 Qoder dry-run 和 path conflict 测试。
- 新增 `meta-flow cr impact-report --project-root .`，用于把旧 `impact_surface` 迁移为结构化影响面字段，并输出 capability resolver 结果、未分类 legacy 值和 follow-up candidate。
- `meta-flow cr brief --id <CR-ID> --mode enforce --project-root .` 可用 enforce 模式展示 capability blockers；默认 audit 模式适合盘点。
- 正式 CR 支持结构化影响面字段：`impact_capability_refs`、`impact_feature_refs`、`impact_module_paths`、`impact_policy_refs`、`impact_process_refs`、`impact_runtime_refs`、`impact_data_refs`。
- 项目可通过 `process/project/IMPACT-SURFACE-RULES.yaml` 配置 legacy impact 分类规则；修改规则后应重新运行 impact report、CR lifecycle check 和相关测试。
- CR036 已以 recovery stub 形式关闭为 `READY_WITH_RISK`，保留原始 planning / handoff / formal decision artifact 缺失风险；CR037 已关闭为 `READY`。
- CR155 复盘 follow-up 已完成：CP0 会阻断 scope/authz 矛盾，CP7 会把 CP2 commitments 与 evidence alignment 对齐，缺失 required evidence 不再能以 `PASS_WITH_RISK` 绕过。
- CP8 result 支持 `fact_diff`，用于自动展示承诺、证据、状态、剩余风险和 release decision；release docs 默认从 `RELEASE-CONTEXT.yaml` 派生 compact 摘要，不复制完整 evidence 正文。
- 新增 governance dependency warning：当业务 CR 依赖未关闭 governance CR 可能修改的 policy/authz/roadmap/process 基线时，CP0 可给出 `NEEDS_REVIEW` 级提示。
- CP result 可记录 checker provenance；repository publication authz 与 CR runtime/lake/trading 授权分离，避免把 post-CR git push 误读为业务运行授权。
- CP1 支持 existing use case extension 的分级速通；archive/backups 迁移可从业务 CR diff 中隔离为 housekeeping 风险或独立项。
- 新增 `meta-flow validation run --profile real-lake-readonly`，为真实 lake readonly 验证生成 run ledger、evidence index、rerun comparison、admission summary 和 forbidden operation counter 摘要；默认不执行外部命令，`--execute --command` 需要独立授权。
- Story 管理合并到 `process/DEVELOPMENT-PLAN.yaml` 作为 Story / Wave / status / task 机器真相源；`STORY-BACKLOG.md`、`STORY-STATUS.md` 和 Feature `TASKS.md` 只作为 optional legacy / generated views，并由 `meta-flow story plan-check` 检查 drift。
- CR-045 新增确定性的 CR-aware route planning：未适用 checkpoint 记录为 N/A，不再用 WAIVED 代替；pass-like、失败、授权和 workflow-health stop reason 由 route-driven state transition 做一致性校验。最终 CP7-R6 已关闭全部实现 finding，approved-CP8 边界矩阵 9/9、17 / 113 / 329 分层测试通过。终态 stop reason 的精确路径是 `STATE.current.json.next_action.stop_reason`；dispatch 执行虽为会话观察到的真实任务，但仓库缺少平台签发 receipt，严格 provenance 移交 CR-A S01。
- CR-047 使 stale State/CR/CURRENT、legacy CR index、非幂等 route metadata、clean-clone 根 wrapper 依赖、未分类历史预算和非交互安装示例进入确定性检查；publication preflight 增加 ledger 对象身份回归后，最终本地基线为 401 tests + 70 subtests、Ruff 0、五门 exit 0、3/3 dry-run。没有独立 QA/platform receipt/token telemetry/真实 pilot 时结论保持 `READY_WITH_RISK`。

## 兼容性

- 安装器 CLI 未破坏。
- Qoder 与 Codex 共享 `AGENTS.md` 不产生冲突：platform-tagged managed block 保证各平台内容独立隔离，旧的无标签 block 在下次安装时自动迁移为带标签格式。
- 已 clone 的源码仓库需要同时准备 artifact repo，或由 `meta-flow workspace link --artifact-root <relative-artifact-root>` 指向正确 artifact root；运行态记录不得固化设备相关绝对路径。
- 纯代码项目不强制 workflow eval。
- 外部 adapters 默认 disabled，真实运行需要独立 runtime authorization。
- 既有 `process/STATE.md` 仍可作为人类摘要或 legacy fallback，但新流程默认机器入口是 `process/state/STATE.current.json`。
- 关闭 CR 的完整 Markdown 仍可归档追溯，但默认上下文应读取 CR summary / index。
- 新增治理命令保持零运行时依赖；token 估算使用 `ceil(char_count / 4)`，后续如需精确 tokenizer 可作为可选增强。
- 新增质量治理命令保持零运行时依赖；policy 模板为 YAML 子集，checker 使用仓库既有保守解析器。
- 新增 CR follow-up 治理命令保持零运行时依赖；`validation run` 只有在显式传入 `--execute --command` 时才执行验证命令，并且不会提升 lake write、trading、broker 或 publish 授权。
- CR-045 不改变安装路径、状态 schema、命令参数或外部接口；既有 checkpoint / ledger 不批量迁移或重写。

## 已知风险

| 风险 | 等级 | 处理 |
|---|---|---|
| 本地 eval runner 使用保守 YAML-like parser | LOW | 保持 eval config 简单；复杂嵌套需要后续 CR 引入正式 parser |
| 外部 adapters 只定义 policy | INFO | 真实运行前创建 runtime_authorization CR 或 Spike |
| `process/` 和内部 docs 依赖 symlink | MEDIUM | 缺失或断链时 hard-stop，由用户提供相对项目根的 artifact 目录后再继续 |
| context-budgeted governance 是新命令面 | MEDIUM | 已用 84 项 pytest、delivery guardrail 和端到端 fixture 验证；建议先用 quant-lab redesign bootstrap 进行真实项目试运行 |
| 旧项目迁移仍需项目级判断 | MEDIUM | 本次不强制移动历史 artifact；未来项目默认使用 ledger、summary、packet 和 result JSON 治理 |
| 历史 CR process artifacts 不完整 | MEDIUM | CR036 已完成 recovery closure；CR033-CR035 等更早 CR 是否需要同类 sweep 需后续治理项判断 |
| Story legacy views 仍可能存在 | LOW | `DEVELOPMENT-PLAN.yaml` 是机器真相源；`STORY-BACKLOG.md` / `STORY-STATUS.md` / `TASKS.md` 作为 legacy / generated view 时必须用 `meta-flow story plan-check` 检查 drift |
| CR-045 recovery gate ordering | MEDIUM | CP2 / CP5 为历史 CP6 后的事后恢复审批，审计顺序永久保留且未倒填；CP8 需明示接受该过程风险 |
| CR-045 test cache hygiene | INFO | CP7 发现 ignored Python test caches；Host 在 CP8 前例行清理并重跑 delivery guardrail，重复出现才进入 follow-up tracking |
| CR-045 dispatch platform receipt | MEDIUM | 当前证据为 session-observed，仓库不可独立验证平台调用真实性；移交 CR-A S01 producer contract，不倒填历史 receipt |
| CR-047 inline CP7 / paired Git publication | MEDIUM | 7/7 功能验证通过，但无独立 meta-qa/platform receipt；用户在 CP8 批准消息中另行授权 `meta-flow` 与 `meta-flow-artifacts` 配对 commit/push，结论仍保持 `READY_WITH_RISK`。 |
| CR-047 historical/reference-only warnings | LOW | Doctor exit 0 且 blocker/unclassified=0；21 个 closed/reference-only 超预算和 legacy provenance warning 保持可见，不伪造为无风险。 |

## CR-057 候选发布切片

### 候选身份与边界

| 项 | 值 |
|---|---|
| 当前包版本 | `0.4.0`，本次未修改 `pyproject.toml` 或 `uv.lock` |
| 推荐目标版本 | `0.5.0` candidate；属于新增公共能力的 MINOR 候选，不代表已 tag 或正式发布 |
| 支持平台 | Linux / Python 3.11 |
| Windows | `RISK-055-WIN-001`，deferred / out-of-scope；无 Windows 原生 PASS 声明 |
| CP8 自动预检 | `PASS / READY_WITH_RISK`，仍须人工终验 |
| 非授权动作 | 版本修改、commit、push、merge、tag、正式发布、真实外部项目迁移 |

### 用户可见能力

- `meta-flow project init` 对新项目和已有项目 snapshot seed 生成严格 12 字段 dry-run envelope；非 `NOOP` mutation 必须提供与 source exact OID、PROJECT 原始字节 digest、plan digest 和 decision ref 绑定的一次性 typed authorization。
- release/process 在 dry-run、authorization consumption、apply-final 分别核验 exact OID，共 6 个双仓检查点；snapshot source 在相同阶段另有 3 个只读 OID 检查。
- `project adopt` 只接收 clean、已提交的新格式过程快照；legacy shared-artifact 子目录不进入 adopt，也不复制全量 CR/CP/Story/ledger。
- `project recover` 对 healthy binding 和 unresolved 场景都输出严格 12 字段 envelope；manifest missing、corrupt JSON、missing fields 或 digest drift 均 fail closed，不猜 ownership、不消费授权、不产生 mutation。
- F1 新项目与 F2 snapshot-only 接入均在隔离 fixture 中通过；第二次相同 init/adopt 返回 `NOOP`。

### 质量证据

| 检查 | 结果 |
|---|---|
| 独立 QA | PASS；F-001 至 F-007 全部关闭 |
| 定向回归 | F-007 direct 4 passed；recovery 10 passed；核心 100 passed；六消费者 103 passed + 15 subtests |
| 全仓回归 | 962 passed + 105 subtests |
| 静态与交付门 | Ruff 0 error；pycompile exit 0；delivery guardrail exit 0 / OK |
| 禁止边界 | 绝对 process 路径、未知 changed path、新依赖、source write、legacy/external mutation、Windows PASS 声明均为 0 |

### 已知风险与后续

| 风险 / 后续 | 处置 |
|---|---|
| `RISK-057-GOV-SEQ-001` | release main 已先于 CP8 人工终验合并；历史事实保留，不倒填或自动回滚，CP8 只能以 `READY_WITH_RISK` 供人工接受或拒绝 |
| `FU-CR057-001` | “CP8 必须先于 commit/push”已 accepted / approved_not_started；只登记候选，CR-057 关闭前不创建或启动新的正式 CR |
| `RISK-055-WIN-001` | 继续 deferred / out-of-scope，不阻塞 Linux 候选，也不声称 Windows 原生验证通过 |
