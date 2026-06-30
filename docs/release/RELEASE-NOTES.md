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

## 用户可见变化

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

## 已知风险

| 风险 | 等级 | 处理 |
|---|---|---|
| 本地 eval runner 使用保守 YAML-like parser | LOW | 保持 eval config 简单；复杂嵌套需要后续 CR 引入正式 parser |
| 外部 adapters 只定义 policy | INFO | 真实运行前创建 runtime_authorization CR 或 Spike |
| `process/` 和内部 docs 依赖 symlink | MEDIUM | 缺失或断链时 hard-stop，由用户提供相对项目根的 artifact 目录后再继续 |
| context-budgeted governance 是新命令面 | MEDIUM | 已用 84 项 pytest、delivery guardrail 和端到端 fixture 验证；建议先用 quant-lab redesign bootstrap 进行真实项目试运行 |
| 旧项目迁移仍需项目级判断 | MEDIUM | 本次不强制移动历史 artifact；未来项目默认使用 ledger、summary、packet 和 result JSON 治理 |
