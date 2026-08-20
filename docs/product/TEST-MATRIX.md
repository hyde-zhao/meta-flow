---
status: confirmed
version: "1.3"
source_scenarios: "docs/product/SCENARIOS.yaml"
source_change: "CR-071 + CR-072 + CR-073"
formal_cp2_status: approved
confirmed_by: "user"
confirmed_at: "2026-08-19T14:05:17Z"
formal_cp2_approval_ref: "CR073-CP2-USER-DECISION-20260819-V1"
---

# CR-071 Test Matrix

## 修订记录

| 版本 | 日期 | 变更要点 | 状态影响 |
|---|---|---|---|
| 1.0 | 2026-08-15 | 建立 18 行 planned 覆盖矩阵 | formal CP2 pending |
| 1.1 | 2026-08-15 | 将 CP2 revision 2 六项 delta 绑定到既有场景，并增加 CP4 强制盘点 | 行数仍为 18；不声明测试已实现或执行 |
| 1.2 | 2026-08-18 | 追加 CR-072 12 条 Package 验证场景 | 行数为 30；均为 planned，不声明实现、运行、qualification 或发布 |
| 1.3 | 2026-08-19 | 回填 CR-072 CP6/聚合 CP7 fixture 与 contract 证据 | 12 条均已绑定自动化；SCN-072-09/11 的真实发布/安装态运行保持 conditional-runtime |

## 覆盖矩阵

| Scenario ID | Requirement ID | Story ID | 测试类型 | 自动化状态 | 手工验收状态 | 测试文件 / 命令 | 未覆盖原因 |
|---|---|---|---|---|---|---|---|
| SCN-MF1-01 | REQ-MF1-01, REQ-MF1-02, REQ-MF1-03 | ST-MF1 | integration / contract | planned | pending | `planned: shared validation core preflight/apply normalized decision parity + preflight mutation=0 fixture` | — |
| SCN-MF1-02 | REQ-MF1-01, REQ-MF1-02, REQ-MF1-03 | ST-N-MF1 | regression / fail-closed | planned | pending | `planned: invalid snapshot shared-core item/error parity + preflight mutation=0 fixture` | — |
| SCN-MF1-03 | REQ-MF1-02 | ST-N-MF1 | precheck / contract | planned | pending | `planned: on-touch closure fixture` | — |
| SCN-MF2-01 | REQ-MF2-01, REQ-MF2-02, REQ-MF2-03 | ST-MF2 | integration / contract | planned | pending | `planned: BL-001 revision>1 legal supersession admission + append-only E2E fixture` | — |
| SCN-MF2-02 | REQ-MF2-01, REQ-MF2-02, REQ-MF2-03 | ST-N-MF2 | regression / fail-closed | planned | pending | `planned: missing predecessor/inventory admission, stale preimage and unknown path fixture` | — |
| SCN-MF2-03 | REQ-MF2-02, REQ-MF2-03 | ST-N-MF2 | permission / security | planned | pending | `planned: typed authorization denial fixture` | — |
| SCN-MF3-01 | REQ-MF3-01, REQ-MF3-02, REQ-MF3-03 | ST-MF3 | unit / contract | planned | pending | `planned: release/process typed ref fixture` | — |
| SCN-MF3-02 | REQ-MF3-01, REQ-MF3-02 | ST-N-MF3 | security / fail-closed | planned | pending | `planned: unknown role and ambiguous prefix fixture` | — |
| SCN-MF3-03 | REQ-MF3-03 | ST-N-MF3 | migration / compatibility | planned | pending | `planned: read-old/write-new v1 writer=0, residual=0, ambiguous/misread=100%, two-snapshot observed=0 fixture` | — |
| SCN-MF4-01 | REQ-MF4-01, REQ-MF4-02, REQ-MF4-03 | ST-MF4 | contract / integration | planned | pending | `planned: canonical validation policy layer-plan fixture` | — |
| SCN-MF4-02 | REQ-MF4-01, REQ-MF4-02, REQ-MF4-03 | ST-N-MF4 | regression / migration | planned | pending | `planned: legacy no-prohibition semantics fixture` | — |
| SCN-MF4-03 | REQ-MF4-02, REQ-MF4-03 | ST-N-MF4 | compatibility / boundary | planned | pending | `planned: canonical-v1 decision equivalence + quantified reader-retirement gate matrix` | — |
| SCN-MF5-01 | REQ-MF5-01, REQ-MF5-02, REQ-MF5-03 | ST-MF5 | integration / evidence | planned | pending | `planned: canonical semantic-equivalence matrix; equivalent runner/environment false rejection count=0` | — |
| SCN-MF5-02 | REQ-MF5-01, REQ-MF5-02 | ST-N-MF5 | regression / evidence | planned | pending | `planned: safety-relevant non-equivalent drift rejection=100% matrix` | — |
| SCN-MF5-03 | REQ-MF5-02, REQ-MF5-03 | ST-N-MF5 | external-failure / recovery | planned | pending | `planned: missing evidence/provenance fixture` | — |
| SCN-MF6-01 | REQ-MF6-01, REQ-MF6-02, REQ-MF6-03 | ST-MF6 | projection / integration | planned | pending | `planned: unregistered failure and baseline drift fixture` | — |
| SCN-MF6-02 | REQ-MF6-01, REQ-MF6-02 | ST-N-MF6 | security / fail-closed | planned | pending | `planned: missing ownership evidence fail-closed fixture` | — |
| SCN-MF6-03 | REQ-MF6-03 | ST-N-MF6 | recovery / boundary | planned | pending | `planned: add valid evidence → one reprojection exits block/converges; no manual derived-state edits; stable-source no-op` | — |
| SCN-072-01 | REQ-072-01, REQ-072-02 | ST-072-PLAN | compiler / contract | covered | verified | `tests/test_cr072_package_compiler.py`; `process/docs/features/cr072-aggregate-release/VERIFICATION.md` | — |
| SCN-072-02 | REQ-072-01, REQ-072-02, REQ-072-12 | ST-N-072-PLAN | precheck / fail-closed | covered | verified | `tests/test_cr072_package_compiler.py` negative/zero-write matrix | — |
| SCN-072-03 | REQ-072-03, REQ-072-04 | ST-072-CLOSURE | closure / integration | covered | verified | `tests/test_cr072_closure_build.py` direct/transitive/affected-only matrix | — |
| SCN-072-04 | REQ-072-03, REQ-072-04 | ST-N-072-CLOSURE | boundary / recovery | covered | verified | `tests/test_cr072_closure_build.py` invalid SHA/graph/no-op matrix | — |
| SCN-072-05 | REQ-072-05 | ST-072-COST | metrics / no-op | covered | verified | `tests/test_cr072_process_cost.py`; `meta-flow package cost-report --cr CR-072` | — |
| SCN-072-06 | REQ-072-05, REQ-072-06, REQ-072-10 | ST-N-072-COST | hard-gate / failure | covered | verified | `tests/test_cr072_process_cost.py`, `tests/test_cr072_release_order.py` | — |
| SCN-072-07 | REQ-072-07, REQ-072-08 | ST-072-SEMVER | SemVer / contract | covered | verified | `tests/test_cr072_semver_decision.py`; production CLI dogfood | — |
| SCN-072-08 | REQ-072-07, REQ-072-08 | ST-N-072-SEMVER | compatibility / fail-closed | covered | verified | `tests/test_cr072_semver_decision.py` breaking/reuse/cross-version matrix | — |
| SCN-072-09 | REQ-072-09, REQ-072-10 | ST-072-RELEASE | release-order / manual | covered | conditional-runtime | `tests/test_cr072_release_order.py`, `tests/test_cr072_provider_source_qualification.py` | 真实 freeze/qualification/build/canary/tag/release 仍需独立授权 |
| SCN-072-10 | REQ-072-09, REQ-072-10, REQ-072-12 | ST-N-072-RELEASE | state-machine / recovery | covered | verified | `tests/test_cr072_release_order.py` drift/order/intermediate/recovery matrix | — |
| SCN-072-11 | REQ-072-11 | ST-072-CONSUMER | consumer / canary | covered | conditional-runtime | `tests/test_cr072_provider_canary_contract.py`, `tests/test_cr072_release_asset_completeness.py` | 安装态 published asset canary 等待最终独立授权 |
| SCN-072-12 | REQ-072-11, REQ-072-12 | ST-N-072-CONSUMER | permission / fail-closed | covered | verified | `tests/test_cr072_provider_canary_contract.py` missing asset/CLI/home/auth negative matrix | — |

## 覆盖统计

| 维度 | 总数 | planned | covered | gap | waived | 说明 |
|---|---:|---:|---:|---:|---:|---|
| HIGH 场景 | 18 | 18 | 0 | 0 | 0 | CP2 产品基线只定义验证入口；实现后在 CP6/CP7 回填 covered |
| 正向场景 | 6 | 6 | 0 | 0 | 0 | MF-1～MF-6 各 1 条 |
| 负向场景 | 6 | 6 | 0 | 0 | 0 | MF-1～MF-6 各 1 条 |
| 边界 / 空数据 | 3 | 3 | 0 | 0 | 0 | typed ref、validation policy、projection recovery/no-op |
| 权限 / 安全场景 | 3 | 3 | 0 | 0 | 0 | scope authorization、typed ref ambiguity、unknown failure owner |
| 外部失败场景 | 1 | 1 | 0 | 0 | 0 | receipt evidence/provenance 不可读 |
| precheck 场景 | 1 | 1 | 0 | 0 | 0 | on-touch obligation closure |
| CR-072 Package 场景 | 12 | 0 | 12 | 0 | 0 | 10 条 fixture/contract 已 verified；SCN-072-09/11 已覆盖但真实发布/安装态执行为 conditional-runtime |

## 需求覆盖追踪

| MF | Use Case | Requirements | Scenarios | Stories | 状态 |
|---|---|---|---|---|---|
| MF-1 | UC-WORK-PREFLIGHT | REQ-MF1-01～03 | SCN-MF1-01～03 | ST-MF1, ST-N-MF1 | covered-by-plan |
| MF-2 | UC-SCOPE-AMENDMENT | REQ-MF2-01～03 | SCN-MF2-01～03 | ST-MF2, ST-N-MF2 | covered-by-plan |
| MF-3 | UC-TYPED-REFS | REQ-MF3-01～03 | SCN-MF3-01～03 | ST-MF3, ST-N-MF3 | covered-by-plan |
| MF-4 | UC-FULL-REGRESSION-SEMANTICS | REQ-MF4-01～03 | SCN-MF4-01～03 | ST-MF4, ST-N-MF4 | covered-by-plan |
| MF-5 | UC-VALIDATION-REUSE | REQ-MF5-01～03 | SCN-MF5-01～03 | ST-MF5, ST-N-MF5 | covered-by-plan |
| MF-6 | UC-UNREGISTERED-FAILURE-VISIBILITY | REQ-MF6-01～03 | SCN-MF6-01～03 | ST-MF6, ST-N-MF6 | covered-by-plan |
| 072-1 | UC-PLAN-COMPILER | REQ-072-01～02 | SCN-072-01～02 | ST-072-PLAN, ST-N-072-PLAN | covered-by-plan |
| 072-2 | UC-CLOSURE-BUILD | REQ-072-03～04 | SCN-072-03～04 | ST-072-CLOSURE, ST-N-072-CLOSURE | covered-by-plan |
| 072-3 | UC-PROCESS-COST | REQ-072-05～06 | SCN-072-05～06 | ST-072-COST, ST-N-072-COST | covered-by-plan |
| 072-4 | UC-SEMVER-DECISION | REQ-072-07～08 | SCN-072-07～08 | ST-072-SEMVER, ST-N-072-SEMVER | covered-by-plan |
| 072-5 | UC-RELEASE-ORDER | REQ-072-09～10, REQ-072-12 | SCN-072-09～10 | ST-072-RELEASE, ST-N-072-RELEASE | covered-by-plan |
| 072-6 | UC-PUBLISHED-ASSET-CONSUMER | REQ-072-11～12 | SCN-072-11～12 | ST-072-CONSUMER, ST-N-072-CONSUMER | covered-by-plan |

## 缺口处理

| Gap ID | 来源 | 缺口 | 阻断等级 | 推荐处理 | 责任方 |
|---|---|---|---|---|---|
| GAP-000 | 全部场景 | 当前无产品级覆盖缺口；CR-072 已回填 12/12，既有 MF 场景仍按各自历史状态维护 | OPTIONAL | 聚合 CP7 继续绑定验证报告；真实 runtime 项仅在独立授权后更新执行状态 | meta-qa |

## CP2 Revision 2 Delta Trace

| Delta | 产品合同落点 | 场景 / 矩阵落点 | 关闭判定 |
|---|---|---|---|
| REV-01 | BL-001 → MF-2 enabling prerequisite；不新增 MF-7 | SCN-MF2-01/02 | MF-2 实现与 E2E 前须通过 revision>1 admission |
| REV-02 | preflight/apply 单一 validation core/decision graph | SCN-MF1-01/02 | 同快照 normalized decision 一致，仅 orchestration/presentation 不同 |
| REV-03 | read-old/write-new 量化门槛 | SCN-MF3-03、SCN-MF4-03 | writer=0、residual=0、ambiguous/misread=100%、two snapshots observed=0 |
| REV-04 | canonical semantic-equivalence matrix | SCN-MF5-01/02 | 等价误拒=0；安全相关非等价漂移拒绝=100% |
| REV-05 | fail closed → 补证 → 一次 reprojection 收敛 | SCN-MF6-02/03 | 不手改派生状态且一次重投影退出阻断 |
| REV-06 | bootstrap source/test 强制盘点 | CP4 inventory（下表） | CP4 必须分解；本轮不声称实现或验证 |

## CP4 Mandatory Decomposition / Regression Inventory

| Inventory ID | 类型 | 对象 | CP4 要求 | 当前声明 |
|---|---|---|---|---|
| CP4-SRC-01 | source | `meta_flow/workflow/cr_cli.py` | mandatory decomposition | 未实现、未验证 |
| CP4-SRC-02 | source | `meta_flow/workflow/cr_index.py` | mandatory decomposition | 未实现、未验证 |
| CP4-SRC-03 | source | `meta_flow/work/model.py` | mandatory decomposition | 未实现、未验证 |
| CP4-SRC-04 | source | `meta_flow/state/formal_projection.py` | mandatory decomposition | 未实现、未验证 |
| CP4-TST-01 | test | `tests/test_cr_cli.py` | mandatory regression inventory | 未执行、不声称通过 |
| CP4-TST-02 | test | `tests/test_cr_index.py` | mandatory regression inventory | 未执行、不声称通过 |
| CP4-TST-03 | test | `tests/test_vnext_work_model_lifecycle.py` | mandatory regression inventory | 未执行、不声称通过 |
| CP4-TST-04 | test | `tests/test_state_formal_projection.py` | mandatory regression inventory | 未执行、不声称通过 |

## 人工验收边界

- 本矩阵中的 `planned` 仍不声明测试已经实现或运行；CR-072 行已按 1.3 回填为 `covered`。
- CP2 approve 只冻结产品范围和推荐合同，不授权真实运行、外部写入、发布或安装。
- targeted → compatibility → full 的执行证据必须在后续分层验证阶段产生。

## CR-073 增量追踪（CP2 已确认）

| 场景 | REQ | 旅程 | 类型 | 当前状态 | 验证入口 / 边界 |
|---|---|---|---|---|---|
| SCN-073-01/02 | REQ-073-01 | J1 | 正向/负向 | planned | historical-reframe audit；不得改写历史 PASS |
| SCN-073-03/04 | REQ-073-02 | J1 | precheck/边界 | planned | zero-write lifecycle/index/tuple/manifest |
| SCN-073-05/06 | REQ-073-03/04 | J2 | 正向/失败恢复 | planned | additive amend + orphan failure projection |
| SCN-073-07/08 | REQ-073-05 | J3 | 正向/负向 | planned | identity reuse + drift invalidation |
| SCN-073-09/10 | REQ-073-06 | J1/J2 | 多对多覆盖 | planned | 六轮事故无漏行；R3 人工项显式归属 |
| SCN-073-11 | REQ-073-07 | J3 | 权限 | blocked-until-authorized | source-candidate 外部 typed authorization |
| SCN-073-12 | REQ-073-08 | J3 | 发布后受害者 | deferred | installed-artifact replay = 下一发布硬门 |
