---
status: draft
version: "1.1"
confirmed_by: ""
confirmed_at: ""
source_change: "CR-071"
formal_cp2_status: pending
---

# CR-071 MVP Scope

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-08-15 | meta-pm | 固定 MF-1～MF-6 推荐 MVP 边界 |
| 1.1 | 2026-08-15 | meta-pm | 吸收 CP2 revision 2 六项 delta；BL-001 改为 MF-2 enabling prerequisite，不新增 MF-7 |

## 本轮目标

| 目标 ID | 用户 outcome | 度量方式 | 目标值 | 来源 |
|---|---|---|---|---|
| GOAL-01 | Work apply 前可一次发现 lifecycle 机械错误且两入口不漂移 | shared-core preflight/apply decision parity fixture | normalized decision=100% 一致；preflight mutation=0 | UC-WORK-PREFLIGHT；SM-01 |
| GOAL-02 | scope 可以修订但不能改写授权历史 | revision>1 admission 与 amendment revision/authz/invalidation 完整率 | 100%；BL-001 未通过则 MF-2 blocked | UC-SCOPE-AMENDMENT；SM-02 |
| GOAL-03 | 公共引用与回归字段没有隐式相反语义且旧 reader 有量化出口 | canonical/legacy migration fixtures | writer v1=0；residual=0；ambiguous/misread=100%；two snapshots observed=0 | UC-TYPED-REFS；UC-FULL-REGRESSION-SEMANTICS；SM-06 |
| GOAL-04 | 可安全减少重复验证且失败投影可自动恢复 | semantic-equivalence 与 two-stage projection fixture | 等价误拒=0；安全漂移拒绝=100%；补证后一次 reprojection 收敛 | UC-VALIDATION-REUSE；UC-UNREGISTERED-FAILURE-VISIBILITY；SM-03/04 |

## In Scope

| Scope ID | 内容 | 覆盖 Story | 必须完成原因 | 验证入口 |
|---|---|---|---|---|
| IN-01 | MF-1 全生命周期零写 `work init-preflight` 与 apply 的 shared validation core/decision graph | ST-MF1, ST-N-MF1 | 消除 apply 后才发现错误及入口规则漂移 | SCN-MF1-01～03；TEST-MATRIX |
| IN-02 | MF-2 append-only `scope-amend`、重新授权与证据失效；BL-001 revision>1 admission 为硬前置 | ST-MF2, ST-N-MF2 | 在不削弱 deny-default 下允许合法修订并修复 supersession 接纳前提 | SCN-MF2-01～03；TEST-MATRIX |
| IN-03 | MF-3 repository-role typed ref、统一前缀与 read-old/write-new 量化迁移 | ST-MF3, ST-N-MF3 | 消除跨仓引用歧义并让 reader 退役可证明 | SCN-MF3-01～03；TEST-MATRIX |
| IN-04 | MF-4 非禁令式 full regression 执行策略语义与 read-old/write-new 迁移 | ST-MF4, ST-N-MF4 | 防止 required full 层被误跳过和 v1 双重真相 | SCN-MF4-01～03；TEST-MATRIX |
| IN-05 | MF-5 canonical semantic identity receipt reuse 与失效层重跑 | ST-MF5, ST-N-MF5 | 避免等价 fixture 误拒并 100% 拒绝安全漂移 | SCN-MF5-01～03；TEST-MATRIX |
| IN-06 | MF-6 unregistered failure/baseline drift projection 与补证后单次重投影恢复 | ST-MF6, ST-N-MF6 | 防止未知失败被投影成健康或靠手改派生状态恢复 | SCN-MF6-01～03；TEST-MATRIX |

## Out of Scope

| Scope ID | 内容 | 排除原因 | 影响 | 重启条件 |
|---|---|---|---|---|
| OUT-01 | quant-lab READ-PLAN、授权瘦身、Stage 3 绿色基线和项目侧 supersession 实践 | 用户已固定 Meta Flow 本体边界 | 不在本仓形成第二套项目真相 | 外部项目独立授权、独立 Work/CR 与项目证据齐备 |
| OUT-02 | quant-lab 仓库任何读写或验证执行 | 未授权外部项目操作 | 本 CR 只证明 Meta Flow 公共能力 | 取得独立 typed authorization 后由项目侧流程处理 |
| OUT-03 | 真实 runtime、网络、凭据、生产写与真实安装 | CR-071 明确不授权 | 本地 fixture/dry-run 不能宣称 production-ready | 独立运行授权和运行时风险门通过 |
| OUT-04 | commit、push、merge、tag、publish、release | 仓库 publication 需独立授权 | CP2/CP8 approve 均不扩大权限 | 独立 typed publication authorization |
| OUT-05 | CP2 前的 HLD、技术 Story 拆分、LLD 和实现 | 产品基线尚未冻结 | 后续阶段保持阻塞 | CP2 approved 后按 route plan 推进 |

## Deferred

| Deferred ID | 来源 | 内容 | 延后原因 | 后续处理 |
|---|---|---|---|---|
| DEF-02 | SGA-02 | legacy reader 的实际退役日期 | 当前已定义量化终止指标，日期仍需迁移观测和后续正式批准 | backlog / follow-up |

## Enabling Prerequisite

| Item ID | 归属 | 进入条件 | 退出条件 | 边界 |
|---|---|---|---|---|
| BL-001 | MF-2 | MF-2 实现分解或 E2E 准备开始 | revision>1 legal supersession admission 确定接纳 predecessor/inventory，失败路径 fail closed | current-scope-required；不是 MF-7；本 CP2 不实现 |

## CP3 / CP4 Downstream Constraints

- CP3 必须把 preflight/apply 的单一 shared validation core/decision graph 作为 architecture invariant；仅 orchestration/presentation 可以不同。
- CP4 mandatory decomposition/regression inventory 必须包含 `meta_flow/workflow/cr_cli.py`、`meta_flow/workflow/cr_index.py`、`meta_flow/work/model.py`、`meta_flow/state/formal_projection.py` 及 `tests/test_cr_cli.py`、`tests/test_cr_index.py`、`tests/test_vnext_work_model_lifecycle.py`、`tests/test_state_formal_projection.py`。
- 上述清单不表示这些对象已经实现 MF 能力或已经验证。

## 人工决策项

| Decision ID | 决策类型 | 问题 | 推荐方案 | 备选方案 | 推荐 / 备选优劣 | 影响 / 风险 | 回退 / 切换条件 |
|---|---|---|---|---|---|---|---|
| CP2-DQ-01 | scope | 是否冻结 revision 2：MF-1～MF-6、BL-001 作为 MF-2 enabling prerequisite、CP3 shared-core invariant、CP4 四源码/四测试 mandatory inventory，且不新增 MF-7？ | 冻结 revision 2 全部范围并进入 CP3 | A. 暂缓确认；B. 只冻结 MF-1/MF-2 | 推荐完整吸收六项 review delta 并保持共享安全边界和迁移顺序；暂缓最稳但阻塞全部设计；缩小范围会重新打开合同歧义与失败恢复缺口 | architecture-major 范围、验证成本、CP3 invariant 与 CP4 decomposition/regression inventory | 若任一 P0 AC、BL-001 归属或 mandatory inventory 需修改，回 requirement-clarification 新 revision |
| CP2-DQ-02 | implementation | 是否正式冻结 review delta 指定的 read-old/write-new 及量化门槛？ | read-old/write-new：读 v1、只写 canonical v2并保留 provenance/诊断；writer=0、residual=0、ambiguous/misread=100%、连续两次 full-validation v1 observed=0 后才可提议退役 | A. dual-write；B. hard cutover | 推荐兼顾迁移和单一新真相；dual-write 扩大一致性成本；hard cutover 迁移风险最高 | MF-3/MF-4 migration、测试矩阵、回退和维护成本 | formal CP2 未批准前不得实施或退役；若 reader 无法无歧义归一化则阻断该输入 |

## MVP 成功判定

- 六个 In Scope 能力均有正向、负向/边界场景和产品 Story。
- P0/P1 产品需求缺口为 0，CP2 人工批准仍为独立门。
- 后续 targeted、compatibility、full、contract、migration、projection、fail-closed、recovery 验证全部可由 TEST-MATRIX 回链。
