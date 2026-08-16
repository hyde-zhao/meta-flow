---
status: draft
version: "1.1"
source_scenarios: "docs/product/SCENARIOS.yaml"
source_change: "CR-071"
formal_cp2_status: pending
---

# CR-071 Test Matrix

## 修订记录

| 版本 | 日期 | 变更要点 | 状态影响 |
|---|---|---|---|
| 1.0 | 2026-08-15 | 建立 18 行 planned 覆盖矩阵 | formal CP2 pending |
| 1.1 | 2026-08-15 | 将 CP2 revision 2 六项 delta 绑定到既有场景，并增加 CP4 强制盘点 | 行数仍为 18；不声明测试已实现或执行 |

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

## 需求覆盖追踪

| MF | Use Case | Requirements | Scenarios | Stories | 状态 |
|---|---|---|---|---|---|
| MF-1 | UC-WORK-PREFLIGHT | REQ-MF1-01～03 | SCN-MF1-01～03 | ST-MF1, ST-N-MF1 | covered-by-plan |
| MF-2 | UC-SCOPE-AMENDMENT | REQ-MF2-01～03 | SCN-MF2-01～03 | ST-MF2, ST-N-MF2 | covered-by-plan |
| MF-3 | UC-TYPED-REFS | REQ-MF3-01～03 | SCN-MF3-01～03 | ST-MF3, ST-N-MF3 | covered-by-plan |
| MF-4 | UC-FULL-REGRESSION-SEMANTICS | REQ-MF4-01～03 | SCN-MF4-01～03 | ST-MF4, ST-N-MF4 | covered-by-plan |
| MF-5 | UC-VALIDATION-REUSE | REQ-MF5-01～03 | SCN-MF5-01～03 | ST-MF5, ST-N-MF5 | covered-by-plan |
| MF-6 | UC-UNREGISTERED-FAILURE-VISIBILITY | REQ-MF6-01～03 | SCN-MF6-01～03 | ST-MF6, ST-N-MF6 | covered-by-plan |

## 缺口处理

| Gap ID | 来源 | 缺口 | 阻断等级 | 推荐处理 | 责任方 |
|---|---|---|---|---|---|
| GAP-000 | 全部场景 | 当前无产品级覆盖缺口；自动化尚处于 planned 是 CP2 阶段预期状态 | OPTIONAL | CP4 分解后绑定真实测试文件，CP6/CP7 回填 covered 和执行证据 | meta-se / meta-dev / meta-qa |

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

- 本矩阵中的 `planned` 不声明测试已经实现或运行。
- CP2 approve 只冻结产品范围和推荐合同，不授权真实运行、外部写入、发布或安装。
- targeted → compatibility → full 的执行证据必须在后续分层验证阶段产生。
