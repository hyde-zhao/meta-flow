---
project_id: "meta-flow"
release_scope: "meta-flow-0.6.0-candidate"
release_artifact_profile: "full"
release_decision: "NOT_READY"
created_at: "2026-06-17T13:49:25+08:00"
updated_at: "2026-08-18T09:56:27+08:00"
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
| 1.16-candidate | 2026-07-23 | host-orchestrator | CR-058 治理执行闭环候选：固化 G2 CP8-before-publication、G0/G1 profile N/A、canonical truth、失败恢复上限、leaf path 计数、native projection 与 usage 降本闭环；独立 CP7 PASS，CP8 推荐 `READY_WITH_RISK`。 |
| 1.17-candidate | 2026-07-27 | host-orchestrator / meta-qa-critical | CR-061 治理内核投影收敛候选：统一 terminal-success、dispatch identity、Story admission、read-expansion、状态投影、ledger migration 和 Public Operation Contract Registry；C0 及独立 CP7 PASS，等待 CP8 人工终验。 |
| 1.18-candidate | 2026-08-10 | host-orchestrator / meta-qa-critical | CR-069 有界执行控制内核：产品实现已作为 `4030ff1654d2e6f552f90bb6f23604117e41940d` 推送；CP7 技术验证 PASS，但 cost closure 为不可豁免 `FAIL`，因此发布就绪保持 `NOT_READY`。 |
| 1.19 | 2026-08-13 | Codex | 将已验证的 provider 修复收敛为 `0.4.1`：补齐 typed check artifact、checkpoint successor、dispatch correction/closure、共享治理投影 lineage；轮换 activation receipt v2，并完成 targeted、compatibility、full、构建和安装 dry-run。 |
| 1.20 | 2026-08-13 | Codex | 发布 `0.5.0`：统一 duplicate legacy generation 语义，增加 Work-init 持久事务与 native inspect/recover，并将 State/CURRENT/governance 一致性纳入成功门。 |
| 1.21 | 2026-08-14 | Codex | 为 `0.5.0` provider 补充 typed `work publication-close`：精确解释暂停后受权 publication OID 前进，保持普通 resume fail-closed，并原子关闭 Work 与刷新治理/State 投影；轮换 activation receipt v3。 |
| 1.22-candidate | 2026-08-14 | Codex | 扩展 `work publication-close` 的批量发布契约：新增 V2 exact path coverage、prior Work/PASS 归属、candidate-set digest、recovery Work pending scope 与仓外 authorization 防漂移，同时保留 V1 兼容。 |
| 1.23-candidate | 2026-08-14 | Codex | 修复 execution-control repair 角色不可达与 usage hard-stop 丢事件：新增 single-use typed repair admission，保持全局 `repair_max=0` 和单 writer 上限；预算超限事件改为 append-first、executor fail-closed。 |
| 1.24 | 2026-08-14 | Codex | 发布 `0.5.1`：收敛 publication-close V2、typed repair admission、usage append-first 与原生 Phase metadata 五目标事务；轮换 activation receipt v6，并完成双仓资格化。 |
| 1.25 | 2026-08-15 | Codex | 发布 `0.5.2`：增加可复现 provider artifact 身份、严格 clean-install canary、统一 mutation 来源门禁，并把 legacy evidence registry 提升为 Project 持久真相；Phase transition 在写入前验证 post-state CR truth。 |
| 1.26 | 2026-08-16 | Codex | 发布 `0.5.3`：交付 CR-071 的 fail-closed init preflight、受控 scope amendment、typed refs、兼容观测/退役、七维 receipt 复用、投影恢复与 atomic correction 合同；接受三项非本 CR 基线失败且不使用 waiver。 |
| 1.27-candidate | 2026-08-17 | Codex | 0.6.0 Integrity Stabilization 候选：跨对象生命周期同源收敛、typed projection correction、summary owner、闭合 digest policy、scope/objective successor amendment 与结构化错误边界；等待最终 qualification、clean artifact build、canary 和发布门。 |
| 1.28-candidate | 2026-08-17 | Codex | R4/R4a 修复 root dotfile scope admission，使 canonical quality/release 文档成为普通 tracked candidates；此前 qualification 因后续源码变化失效，发布继续保持 NOT_READY。 |
| 1.29-candidate | 2026-08-17 | Codex | final detector requalification 完成：407/407 classified、45/45 incremental dynamic allowlisted、0 unresolved，guardrail 与 2635 项完整回归全绿；继续等待 clean artifact 证据。 |
| 1.30-candidate | 2026-08-18 | Codex | 双仓 source-freeze 前置提交已成对推送且工作树 clean/synced；本次只收敛过时发布事实，最终 product OID 在该 evidence commit 后捕获，再进入隔离 artifact build、provider qualification 与 canary。 |

## 0.6.0 发布切片（候选）

### 当前结论

`0.6.0` 是 MINOR 候选，不是 PATCH。它新增公共操作和 manifest/schema 版本，收紧旧 writer 行为，并修复跨对象真相、summary owner、release digest 与路由错误边界。当前 `release_decision=NOT_READY`：clean source commit、final detector qualification、delivery guardrail 与完整回归已完成；provider artifact qualification、artifact build、isolated canary 和人工发布门尚未完成。

| 项 | 候选结果 |
|---|---|
| 生命周期一致性 | Work close / status / scope amendment 与 State/CURRENT 使用共享 writer lock 和同一 formal truth；R3 已原子替换 Work objective 为 0.6.0 |
| correction | 新增 `state projection-correct` typed transaction；新 correction manifest 使用 V2 identity，使安装态 0.5.3 明确 fail closed；热修期 V1 历史仍可由新 reader 读取 |
| summary owner | `decision_status` 从 canonical gate projection 派生，follow-up 从 release disposition owner 派生；终态 pending、伪造候选和无 owner follow-up 被拒绝 |
| digest policy | source / wheel / install 共用闭合 exclusion policy；receipt 字段保持 V1，策略绑定使用独立 sidecar；symlink、duplicate、outside、tracked-generated fail closed |
| scope/objective successor | `cr scope-amend` 支持 V2 typed objective replacement，并允许授权安全根级 dotfile；V1 历史授权仍可读，V2 revision/receipt 明确记录目标变化并支持晚期回滚 |
| 错误与合同 | route failure 返回结构化错误而非 traceback；`kind=cr + execution_unit` 与 admission 支持域一致；bootstrap writer 归入原子 owner |

### 版本与兼容

- 从 0.5.3 升级必须整体替换 writer、inspector 和 detector baseline；不支持同一过程仓的新旧 writer 混用。
- 0.6.0 reader 可读取热修期间的 V1 correction manifest；0.5.3 reader 对新 V2 correction manifest 返回 `BLOCKED / INVALID`。
- 若 0.6.0 尚未对过程仓执行任何新 writer，可回退程序版本；一旦产生 V2 correction 或其他 0.6.0-only 事务，回退前必须按 `docs/release/ROLLBACK.md` 使用升级前快照和同版本 inspect 验证，禁止直接运行 0.5.3 writer。
- 双仓前置 commit/push 已执行；本轮允许完成发布事实 evidence commit/push、隔离 artifact build、provider qualification 与 canary，仍不授权 tag、GitHub Release、PyPI、外部 consumer 安装、真实生产写、凭据或任何 correction apply。

### 验证摘要（qualification 前）

| 层 | 结果 |
|---|---|
| scope/objective amendment | `10 passed`，含 V1 兼容、V2 正向、CLI mismatch、predecessor drift 与晚期回滚 |
| correction | `17 passed`；真实安装态 0.5.3 对 V2 manifest fail closed |
| A3 digest/provider 组合 | `341 passed + 55 subtests` |
| detector / guardrail | full 407/407 classified、0 ambiguous；incremental dynamic 45/45 allowlisted、0 unresolved、findings=[]；guardrail exit 0 |
| 完整回归 | `2635 passed + 716 subtests + 0 failed + 20 warnings`，用时 583.30 秒 |
| 当前缺口 | clean provider receipt、wheel/sdist、isolated canary 与人工发布门；最终结论保持 NOT_READY |

## 0.5.3 发布切片

### 发布结论

`0.5.3` 是向后兼容的 PATCH 发布。CR-071 九个 Story 已全部实现并完成聚合 CP7；CP8 以 `READY_WITH_RISK` 批准发布。风险接受仅覆盖三个发布前已存在、与 CR-071 无归因关系的 full-suite 失败；`new_failure_count=0`、`waiver=false`、open HIGH/BLOCKER=0。真实 correction append 与 effective-authority cutover 不在本发布授权内，未执行。

| 项 | 结果 |
|---|---|
| 包版本真相 | `pyproject.toml`、`uv.lock`、`meta_flow.__version__` 与 execution-control activation receipt v8 均为 `0.5.3`；v1-v7 receipt 字节保持不可变 |
| Work safety | `work init` 的 plan/apply 共同消费 typed refs、validation policy、directory envelope 与唯一 validation graph；apply 重新采集 OID、dirty inventory 和 preimage，漂移时零写阻断 |
| scope amendment | 新增 append-only successor revision、三目标原子事务、失效传播和真实 CLI；BL-001 admission 前置已闭合 |
| receipt reuse | 七维 concrete equivalence table 只能由精确 loader 消费；evidence digest、basis 或单权威 graph 漂移时拒绝复用 |
| compatibility observation | 可信事件适配、CAS/hash-chain 持久观测、epoch/comparison basis 与只产生 proposal 的 retirement admission |
| projection/correction | missing-evidence-only 恢复与 typed correction lineage/atomic persistence 合同已实现；本次没有执行真实 correction 或 authority cutover |
| provider qualification | 源码分层证据见 `docs/release/PROVIDER-QUALIFICATION-0.5.3.json`；正式 artifact receipt 随 GitHub Release 发布 |

### 验证摘要

| 层 | 结果 |
|---|---|
| targeted | `370 passed + 116 subtests` |
| compatibility | `829 passed + 363 subtests`（一个精确 stale-count repair 后有效结果） |
| independent high-risk subset | `377 passed + 108 subtests` |
| full | `2558 passed + 716 subtests + 3 pre-existing failures`；`new_failure_count=0`、`waiver=false` |
| provider rotation | v8 fixed locator、v1-v7 immutable history、provider-specific `60 passed` |
| decision | aggregate CP7 `PASS_WITH_RISK`；CP8 `READY_WITH_RISK` |

### 升级、兼容与回滚

- 从 0.5.2 升级不批量改写历史 Work、CR、ledger 或 raw findings；新字段和 v2 wire 均保持显式、fail-closed。
- 在真实 consumer mutation 前核验 GitHub Release 的 wheel 与 `ProviderArtifactReceiptV1.json`，并运行 `meta-flow version --format json`。
- scope amendment、correction、authority cutover 与兼容 reader retirement 均必须走各自原生 plan/apply 和独立 typed authorization；发布批准不能替代运行授权。
- 回滚到 0.5.2 前先确认没有 0.5.3 创建的非终态事务；terminal successor、receipt 与观测历史保留，不得删除或改写。
- 本发布不上传 PyPI，不安装或修改 quant-lab 等 consumer，不执行真实 correction/cutover、生产 runtime、凭据、NAS、模拟盘、实盘或交易操作。

## 0.5.2 发布切片

### 发布结论

`0.5.2` 是用户指定的向后兼容 PATCH 发布。它解决“同一版本可能来自不同 dirty editable 源码”的供应链歧义，并补齐跨 Phase legacy evidence 的长期 owner 与 transition post-state 门禁。旧 CR 原文、native CR index、历史 lifecycle event 和既有 terminal transaction 均不改写。

| 项 | 结果 |
|---|---|
| 包版本真相 | `pyproject.toml`、`uv.lock` 与 `meta_flow.__version__` 均为 `0.5.2`；execution-control receipt v6 继续只约束其未变化的 0.5.1 owner source set |
| 运行来源身份 | 新增 `meta-flow --version` 与 `meta-flow version --format json`，报告 distribution、module path、source commit/dirty、editable、artifact/capability/payload digest 与 release readiness |
| mutation gate | 外部 consumer mutation 默认要求 clean、exact provider delivery；dirty editable source 只允许显式 development 模式和只读/诊断操作，契约失败返回结构化退出码 2 |
| artifact qualification | 新增 `ProviderArtifactReceiptV1`、clean source qualification 与隔离 wheel canary；忽略 installer 生成的 `uv_cache.json`，在 `direct_url.json` 缺失时由已验证 receipt 提供 artifact SHA，同时仍逐字校验 installed payload 与 capability |
| 安装 provenance | installer 使用完整 source OID，区分 provider checkout 与 consumer `.venv`，把 source/delivery/capability/installed-payload digest 写入安装 manifest |
| Project legacy owner | `PROJECT.yaml` 可声明唯一 `legacy_evidence_registry_ref`；active-Phase-only 读取保留为兼容 fallback，并由 adoption doctor 提示迁移 |
| Phase metadata | 原生 metadata writer 在追加 `CONSUMER-ACCEPTANCE-SPEC.yaml` 时原子维护 Project owner、Phase、governance、STATE、STATE.md 与 CURRENT |
| Phase transition | plan/apply 使用内存 post-state 视图验证 registry continuity、immutable HEAD digest、formal-only CR discovery/index 和 CR tracking；失败零写入并返回稳定 error code |
| provider qualification | 源码分层证据见 `docs/release/PROVIDER-QUALIFICATION-0.5.2.json`；正式 artifact receipt 随 GitHub Release 附件发布 |

### 验证摘要

| 层 | 结果 |
|---|---|
| targeted | `178 passed` |
| compatibility | `146 passed + 21 subtests` |
| full | `2410 passed + 712 subtests` |
| writer hard gate | `399/399 classified`、`36/36 dynamic allowlisted`、`0 ambiguous`、`0 unresolved unallowlisted` |
| static/contract | Ruff、lock、delivery guardrail、双仓 `git diff --check` 通过 |
| artifact | 从 clean release commit 构建 wheel/sdist，严格 receipt 与无 checkout 隔离 canary 作为发布执行门 |

### 升级、兼容与回滚

- 从 0.5.1 升级无需批量改写 consumer 状态；未使用 legacy evidence 的项目不需要新增 Project 字段。
- 仍使用 active Phase registry fallback 的项目可继续只读运行，但 adoption doctor 给出 warning；应通过原生 Phase metadata writer 将同一精确 registry ref 提升为 Project owner。
- Phase transition 现在会在写入前拒绝 registry continuity 或 post-state CR truth 失败；这是 fail-closed 加强，不是把 legacy CR 转成 native CR。
- 正式 consumer mutation 应先核验 `meta-flow version --format json` 的 `release_ready=true`；开发仓内测试需显式 development 模式。
- 回滚到 0.5.1 前必须确认没有依赖 Project-level registry owner 才能保持 CR tracking 的 consumer，且所有 metadata/transition transaction 均为 terminal。
- 本发布不上传 PyPI，不安装或修改 quant-lab 等 consumer，也不执行 consumer recovery、Phase transition、runtime、NAS、模拟盘、实盘或交易操作。

## 0.5.1 发布切片

### 发布结论

`0.5.1` 是用户指定的向后兼容 PATCH 发布。它不改写历史 Work、usage、HANDOFF、base OID 或 Phase 生命周期；新增的公共操作和 typed authorization 均保持 deny-default、plan/apply 分离与 fail-closed。用户已授权提交、推送并发布到 GitHub；不包含消费者项目安装、quant-lab 恢复或 Phase transition apply。

| 项 | 结果 |
|---|---|
| 包版本真相 | `pyproject.toml`、`uv.lock`、`meta_flow.__version__`、provider migration contract 与 activation receipt v6 均为 `0.5.1` |
| publication close | V1 支持单 Work 发布后关闭；V2 对跨 Work 批量发布提供无遗漏、无重复的 path coverage、prior Work/PASS owner、candidate-set 和 recovery Work pending scope 绑定 |
| repair admission | 保持全局 `repair_max=0`；仅凭 single-use `RepairAdmissionAuthorizationV1` 对 blocked predecessor 开放一个 exact repair slot，active writer、OID、scope、blocker 或 expiry 漂移均阻断 |
| usage append-first | 合法 hard-stop usage event 先在锁内幂等追加，再阻断后续 operation；scope、stale digest 和 telemetry 错误继续保持写前阻断 |
| Phase metadata | 新增 `project.phase-metadata plan/apply/inspect/recover`，只允许追加 closed Work typed evidence 或 planned Phase governance baseline ref，并原子维护 Phase、baseline、STATE、STATE.md 与 CURRENT |
| shared lineage | `project.phase-metadata` 成为 canonical successor；native mutation 被 close-inspect 接受，直接编辑 Phase 仍识别为外部漂移 |
| provider qualification | 见 `docs/release/PROVIDER-QUALIFICATION-0.5.1.json` |

### 验证摘要

| 层 | 结果 |
|---|---|
| targeted | `436 passed` |
| compatibility | `146 passed + 21 subtests` |
| full | `2367 passed + 712 subtests` |
| writer hard gate | `393/393 classified`、`30/30 dynamic allowlisted`、`0 ambiguous`、`0 unresolved unallowlisted` |
| public operation registry | `32/32` documented/discovered |
| governance ownership | `9/9` concepts、`48/48` consumers |
| closure | Ruff、lock、delivery guardrail、双平台安装 dry-run、sdist/wheel、Meta Flow dogfood 均通过 |

### 升级、兼容与回滚

- 从 0.5.0 升级不需要批量改写消费者文件；重新安装 exact 0.5.1 provider 后按原 native plan/apply 继续。
- 若存在 publication-close、Work-init 或 Phase metadata 的 `PREPARED`、`APPLYING`、`PARTIAL` 状态，必须先用同版本 inspect/recover 收敛，再升级或降级。
- `project.phase-metadata` 是 result-ref append-only writer，不是通用 Phase 编辑器；不能修改 status、work refs、目标或退出条件。
- 回滚到 0.5.0 前必须确认没有依赖 0.5.1 才能恢复的非终态事务；已提交的 terminal manifest 和 successor receipt 属于审计证据，不删除。
- 本发布不上传 PyPI，不安装或修改 quant-lab 等消费者项目。

## 0.5.0 发布切片

### 发布结论

`0.5.0` 是新增公开恢复操作与事务合同的 MINOR 版本。用户已明确授权本轮完成双仓提交、推送、`v0.5.0` 标签和 GitHub Release；不包含消费者项目安装或 quant-lab 恢复 apply。

| 项 | 结果 |
|---|---|
| 包版本真相 | `pyproject.toml`、`uv.lock`、`meta_flow.__version__`、provider migration contract 与 activation receipt 均为 `0.5.0` |
| legacy generation | 相同 ref、相同 after digest 的无-lineage legacy manifest 形成可审计等价 generation；真实 fork 仍 fail closed |
| Work-init preflight | lineage、predecessor、governance currentness 与 State post-image 可构造性在 domain write 前验证 |
| Work-init transaction | `PREPARED → APPLYING → COMMITTED/RECOVERED/PARTIAL` 持久 manifest，绑定 OID、plan digest 和 exact target bytes/digests |
| native recovery | 新增 `meta-flow work init-inspect` 与 `meta-flow work init-recover`，同时支持新事务和 0.4.1 legacy partial rollback |
| consistency gate | 成功前验证 Project/Phase successor、State formal truth、CURRENT 与 governance baseline；失败时 exact rollback 或可恢复 PARTIAL |
| publication close | 新增 `meta-flow work publication-close`；绑定 immutable HANDOFF、双仓 old/new OID、实时远端、提交/待提交路径、scope、result、plan/target preimage 与 typed authorization，不全局放开 `paused → completed` |
| batch publication close | `WorkPublicationReceiptV2` 对跨 Work changed paths 做无遗漏、无重复覆盖；prior Work 必须 completed/PASS/scope 精确匹配，recovery Work 仅解释其 active scope 内 pending paths，authorization 强制放在双仓外 |
| repair admission | 全局 `repair_max=0` 不变；只有 `RepairAdmissionAuthorizationV1` 对 exact blocked predecessor、root/slice、scope、blocker、OID、expiry 和 single-use claim 全部校验通过时，才允许一个 repair candidate；同 slice active writer 仍阻断，portable `REPAIR-ADMISSION.json` 随 Work-init 原子持久化 |
| usage append-first | stage/total/governance hard-stop event 在锁内幂等追加后阻断 executor；scope、stale digest 与 telemetry failure 继续保持写前阻断 |
| provider qualification | 见 `docs/release/PROVIDER-QUALIFICATION-0.5.0.json` |

### 验证摘要

| 层 | 结果 |
|---|---|
| targeted | `396 passed` |
| compatibility | `222 passed + 21 subtests` |
| full | `2355 passed + 712 subtests` |
| writer hard gate | `393/393 classified`、`30/30 dynamic allowlisted`、`0 ambiguous`、`0 unresolved unallowlisted` |
| consumer fixture | quant-lab 只读 inspect/recovery preview 为 `READY`，关键文件摘要前后不变 |
| closure | Ruff、lock check、delivery guardrail、构建、安装 dry-run与 wheel 内容检查在发布前必须全部通过 |

### 升级与恢复

- 从 0.4.1 升级无需批量改写历史 close manifest；相同 after digest 的重复 legacy generation 会由 canonical evaluator 归一化。
- 0.4.1 已留下的 Work-init `PARTIAL_MUTATION` 必须先运行 `work init-inspect`，再用返回的 exact plan digest 执行 `work init-recover --apply`；`RECOVERED` 后停止并重新 plan。
- 已知 stale governance baseline 现在会使 Work-init plan 返回 `WORK_INIT_GOVERNANCE_PREFLIGHT_BLOCKED`，且 `mutation_count=0`。
- Work 因受权 commit/push 暂停且双仓 OID 已合法前进时，不得覆盖旧 HANDOFF/base OID 或绕过 resume-check；单 Work 发布使用 `WorkPublicationReceiptV1`，跨 Work 批量发布使用带 exact path coverage 的 `WorkPublicationReceiptV2`，先执行 `work publication-close` 零写计划，再以仓外 `WorkPublicationCloseAuthorizationV1` apply。无 publication OID 变化时仍走普通 resume。
- 回滚到 0.4.1 不会自动删除 0.5.0 transaction manifest；回滚前必须确认没有非终结 Work-init transaction。

## 0.4.1 发布切片

### 结论与边界

`0.4.1` 已达到源码提交与远端推送条件。该结论不等于已创建 Git tag、已上传 PyPI、已执行生产安装，也不授权修改任何消费者项目。

| 项 | 结果 |
|---|---|
| 包版本真相 | `pyproject.toml`、`uv.lock`、`meta_flow.__version__` 与 provider receipt 均为 `0.4.1` |
| typed artifact routing | 非 CP 的 `*.result.json` 按 artifact kind 分派；未知类型 fail closed |
| checkpoint successor | 提供 native plan/apply/inspect/recover，保留历史 bytes 并追加 successor 语义 |
| dispatch correction/closure | append-only correction，绑定原始 digest，不从后续成功反推历史 terminal result |
| lifecycle lineage | 合法后继事务可接管共享 Project/Phase generation；无合法后继的当前漂移仍阻断 |
| provider qualification | 见 `docs/release/PROVIDER-QUALIFICATION-0.4.1.json` |
| 发布动作边界 | 本次只提交并推送源码；不创建 tag，不上传包仓库，不安装消费者项目资产 |

### 验证摘要

| 层 | 结果 |
|---|---|
| targeted | `406 passed` |
| compatibility | `159 passed + 10 subtests` |
| full | 隔离 sibling-binding 副本中 `2307 passed + 712 subtests` |
| closure | Ruff、lock check、delivery guardrail、两类安装 dry-run、sdist/wheel 构建与 wheel 内容检查均通过 |

全量验证使用隔离的 sibling-binding 过程仓副本刷新 detector 派生基线；真实 `meta-flow-process` 未被本次源码发布修改。setuptools 仍输出既有 namespace-package discovery warning，但已核对 wheel 中的预期交付资产与版本元数据。

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

## CR-058 候选发布切片

### 用户可见变化

| 能力 | 候选行为 |
|---|---|
| publication eligibility | `repository commit/push` 的 plan 与 apply 都必须从 binding 解析的 canonical refs 重算资格；caller 自证字段不再影响结果 |
| G2 publication | CP8 机器 PASS、人工 approved、native CR closed、exact OID、scope、typed authorization 和目标策略全部一致后才可 READY |
| G0/G1 publication | 消费同一 route/profile 分类输出；只有五项 `NOT_APPLICABLE_BY_PROFILE` 事实和目标预授权成立才可 READY |
| fail closed | evidence missing/stale、digest/OID/target drift 和 formal truth 冲突均在 claim、授权消费、receipt、Git/network mutation 之前 BLOCKED |
| recovery | G0/G1/G2 的 deterministic recovery 上限为 1/2/2；G0 只在剩余 check-group 预算充足时允许一次 |
| changed-path 计量 | 机器统一消费 `git status --porcelain=v1 -z -uall` 的 leaf path；折叠 UI 条目数只用于显示 |
| usage | 80%、100%、超限和 unavailable 使用稳定机器状态；100% 为 `EXCEEDED` |
| native truth | CR、ADR、checkpoint、result、gate 与 ledger 的陈旧联合投影可被检测，不再以局部一致冒充整体一致 |

### 验证结果

- 独立 CP7 最终结论：`PASS`，F-058-CP7-001 至 F-058-CP7-005 全部 `VERIFIED_RESOLVED`。
- 自动证据：publisher 27；定向 161 passed + 48 subtests；R3 定向 56 passed + 6 subtests；最终全仓 1012 passed + 117 subtests。
- 静态与交付：Ruff PASS、隔离 pycompile 24/24、delivery guardrail PASS、mirror 3/3。
- 安全边界：forged/missing/stale/digest/OID/target drift 场景下 authorization consumption、receipt、staged、HEAD/remote mutation 均为 0。

### 降本闭环

- CP8 准备及增量独立复验完成后的最终 usage：319 reads、271 writes、119 check groups、959000 proxy tokens，均严格低于 320/272/120/960000 上限。
- stage coverage 预计 24/24，CP8 人工批准后 user decision interactions 预计 5/6，unknown changed leaf paths=0。
- `CR-057` 没有 actual token telemetry；1,752,000 只是历史授权 proxy ceiling。因此本候选只声明当前硬上限合规和人工交互下降，不声明 actual-to-actual token 降幅，风险记为 `RISK-058-COST-BASELINE-001`。

### 授权边界

CR-058 已完成 CP8 人工批准、native close 和 Work close，最终状态为
`closed/READY_WITH_RISK/cp8_closed`。真实 publication dogfood 额外修复了 canonical
`process/...` 逻辑引用与 WORK 过程根相对 `allowed_reads` 的匹配问题；非 allowlisted 引用继续
fail closed。publication evidence、target policy 和 typed authorization 采用不进入 Git 的单次
运行态对象，以便 commit 后刷新 exact OID 而不制造 process 递归 dirty。

当前用户已单独授权解决该 publication blocker 后执行双仓 commit/push；该授权仍不等于 merge、
tag、正式 release、GOV-006/GOV-007、legacy、真实外部项目或 Windows 原生工作。

## CR-069 候选发布切片

### 候选身份与结论

| 项 | 值 |
|---|---|
| 产品实现提交 | `4030ff1654d2e6f552f90bb6f23604117e41940d` |
| 远端分支 | `origin/main`，已核对远端 exact OID |
| 当前包版本 | `0.4.0`；本 CR 未执行版本提升、tag 或正式 release |
| 推荐后续版本 | `0.5.0` MINOR 候选；需独立版本与 release 授权 |
| 发布资料 profile | `full` |
| CP7 技术结论 | PASS；P0/P1/P2=`0/0/0` |
| CP8 发布就绪 | `NOT_READY` |

### 用户可见变化

- 新增 execution-control kernel，以单一 package-owned policy、闭合 receipt 和 fresh apply proof 控制有界容器 admission。
- 新增 canonical consumer scanner，检查 owner、consumer、dispatcher 与安全敏感私有入口的闭合关系；扫描结果确定性且零写入。
- 新增 provider activation receipt；loader 对 source、manifest、policy 或 evidence 漂移返回 `STALE`/`BLOCKED`，不允许调用方自签绕过。
- 生命周期 failure evidence、occurrence、closure audit 和 projection 使用闭合 typed contract，失败在授权消费和 domain write 之前 fail closed。
- legacy read compatibility 保留为显式只读边界；新写入路径保持 `enforce-new`，不恢复隐式 legacy mutation。

### 质量证据

| 层级 | 结果 |
|---|---|
| targeted | `105 passed` |
| consumer scanner | 两次 READY、stdout byte-identical；262 sources、83 subjects、151 edges、16 classifications、8 个退出计数为 0、mutation=0 |
| closure | `42 passed` |
| compatibility | `412 passed + 29 subtests` |
| full | `1908 passed + 687 subtests` |
| static / diff | Ruff 14 路径 PASS；working-tree 与 cached diff check PASS |
| 独立 QA | PASS；当前 exact preimage P0/P1/P2=`0/0/0` |

### 发布阻断与范围边界

- CR-069 的产品正确性已通过验证，但治理成本闭环为 `FAIL`：reads 1106/96、writes 406/48、check groups 13/13、token proxy 770819/192000、人工交互 8/6。
- 现行 waiver policy 明确禁止把 `FAIL` 或 `NOT_READY` 改写成风险接受，因此不能以“承认超预算”替代 CP8 PASS 或 native close。
- native negative termination 也尚未可用：当前 plan 因 `PROJECT.yaml` / P4 `PHASE.yaml` 不在目标 Work 业务 scope 而 `BLOCKED/0 write`；必须先以单一有界 recovery carrier 修复 control-plane authority，不能手工扩大旧 scope。
- 162 个原 unknown leaf 已 162/162 归入 9 个闭合类别；它们均为当前 CR、已完成 P4 Work 的不可变证据或 active Phase 真相，归档/删除均为 0。归属修复不反向改变超预算事实。
- 本候选未执行安装、升级、tag、正式 release、外部项目操作、legacy 写入或生产运行。产品提交已经推送，不代表 package 已发布或 consumer 已安装。

## CR-061 候选发布切片

### 用户可见变化

| 能力 | 候选行为 |
|---|---|
| terminal-success | CP result、audit、handoff 和 dispatch 统一消费同一原生 projector；不再维护私有成功集合或把 `dispatch_id` 回退为 `event_id` |
| typed dispatch | real subagent 与受限 `inline_fallback` 使用同一 typed attempt 身份；缺 story、canonical role、checkpoint 或批准事实时 fail closed |
| Story admission | CP5→CP6 由原生 projector 投影，contract dependency 在上游 CP6 PASS 后自动满足；virtual bootstrap 不再强制伪造 READY |
| read expansion | 必读但需要扩读登记时由 Host 预登记；公共入口、logical `process/...` 与 append-only migration 使用同一 binding 契约 |
| ledger migration | 旧 dispatch/read-expansion 事件只追加 successor/correction，不删除或改写历史；未知、歧义和无法唯一关联的记录保持 fail closed |
| public operations | 轻量 registry 固定 6 个公共能力，4 条真实 L3 journey；event append、Story projection、read-log、terminate、proposed conflict preview 与 registry check 均可由顶层 CLI 发现 |
| CP8 applicability | `cp applicability-build/check` 在 sibling-binding 下解析逻辑 route plan 和 aggregate 路径，输出绝对 process 路径为 0 |
| status sync | 同一 lifecycle/readiness/gate tuple 在合法过程证据路径增长后仍为 `NO_CHANGE / mutation_count=0`，不追加重复状态事件 |

### 质量证据

- C0 最终 cutover：3/3 bootstrap Story replay、11/11 consumer PASS、bootstrap/legacy consumer=0。
- 独立 CP7：attempt-7 最终 `PASS`，blocker=0、waiver=0；S01 applicability 定向 `4 passed`，paired 公共 build/check PASS。
- 冻结全量基线：`1083 passed + 135 subtests`，workflow eval `2/2`，failure/waiver 公共入口 `12/12`，safety finding=0。
- 增量闭环：S01 `106 passed + 18 subtests`；S05 `73 passed + 22 subtests`；生命周期独立复验 `56 passed + 10 subtests`。
- Public Operation Contract Registry：documented `6/6`、undocumented=0、unknown=0、L3 `4/4`。
- Ruff、隔离 pycompile、delivery guardrail、双仓 diff-check、CR tracking/audit、checkpoint/gate/dispatch ledger 均通过。

### 兼容性与迁移

- 不新增依赖，不修改 `pyproject.toml` 或 `uv.lock`，不改变安装路径。
- `STATE.current.json` 合法缺失时不创建文件；CR-061 通过现有 CR/index/ledger 原生真相继续运行。
- ledger 历史不批量重写；需要规范化的旧事件使用 append-only successor/correction。
- `inline_fallback` 保留为平台真实调度不可用时的受限回退，不作为正常优先路径。

### 风险与授权边界

- `RISK-061-USAGE-CLOSURE-001`：后半程 usage 未形成可与原 420/300/160/3.2M hard cap逐项核对的完整实测总账；用户已要求不中断问题修复，因此本候选不声明预算合规，CP8 推荐 `READY_WITH_RISK`。
- 历史 dispatch ledger 仍有缺 timestamp/receipt 的 legacy warning；当前 CR-061 typed attempt 和 terminal 证据完整，旧行不倒填。
- 本候选未执行真实安装、迁移 apply、native close、commit、push、PR、merge、tag 或 release。CP8 人工批准与 native close 必须先于任何单仓 publication typed authorization。
