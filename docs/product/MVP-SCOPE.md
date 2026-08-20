---
status: confirmed
version: "1.3"
confirmed_by: "user"
confirmed_at: "2026-08-19T14:05:17Z"
source_change: "CR-071 + CR-072 + CR-073"
formal_cp2_status: approved
formal_cp2_approval_ref: "CR073-CP2-USER-DECISION-20260819-V1"
---

# CR-071 MVP Scope

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-08-15 | meta-pm | 固定 MF-1～MF-6 推荐 MVP 边界 |
| 1.1 | 2026-08-15 | meta-pm | 吸收 CP2 revision 2 六项 delta；BL-001 改为 MF-2 enabling prerequisite，不新增 MF-7 |
| 1.2 | 2026-08-18 | meta-pm | 冻结单一 0.6.1 Package、两个 Work 与一次发布血缘 | 保留 CR-071 In/Out/Deferred；新增 CR-072 决策项；CP2 已批准 |

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
| IN-072-01 | 唯一 0.6.1 Package Plan：Work A 稳定化/消费者完整性与 Work B 编译器/成本/发布门 | ST-072-PLAN, ST-N-072-PLAN | 消除双版本/双资格化和散落 package 真相 | SCN-072-01～02 |
| IN-072-02 | Plan compiler、package completeness、priority/ownership/public CLI、affected closure 与 literal SHA | ST-072-CLOSURE, ST-N-072-CLOSURE | 保证执行前决定可裁决且只处理真实影响面 | SCN-072-03～04 |
| IN-072-03 | measure-only 成本、hard-gate 过渡、真实 SemVer 分类与不可复用 bootstrap | ST-072-COST, ST-072-SEMVER 及负向 Story | 防止成本/兼容边界被假阳性掩盖 | SCN-072-05～08 |
| IN-072-04 | 固定 release-order、qualification-once、freeze-drift 恢复和 clean-home published-asset canary contract | ST-072-RELEASE, ST-072-CONSUMER 及负向 Story | 将最终发布约束为一次 aggregate lineage | SCN-072-09～12 |

## Out of Scope

| Scope ID | 内容 | 排除原因 | 影响 | 重启条件 |
|---|---|---|---|---|
| OUT-01 | quant-lab READ-PLAN、授权瘦身、Stage 3 绿色基线和项目侧 supersession 实践 | 用户已固定 Meta Flow 本体边界 | 不在本仓形成第二套项目真相 | 外部项目独立授权、独立 Work/CR 与项目证据齐备 |
| OUT-02 | quant-lab 仓库任何读写或验证执行 | 未授权外部项目操作 | 本 CR 只证明 Meta Flow 公共能力 | 取得独立 typed authorization 后由项目侧流程处理 |
| OUT-03 | 真实 runtime、网络、凭据、生产写与真实安装 | CR-071 明确不授权 | 本地 fixture/dry-run 不能宣称 production-ready | 独立运行授权和运行时风险门通过 |
| OUT-04 | commit、push、merge、tag、publish、release | 仓库 publication 需独立授权 | CP2/CP8 approve 均不扩大权限 | 独立 typed publication authorization |
| OUT-05 | CP2 前的 HLD、技术 Story 拆分、LLD 和实现 | 产品基线尚未冻结 | 后续阶段保持阻塞 | CP2 approved 后按 route plan 推进 |
| OUT-072-01 | 0.7.0、0.6.1-stabilization、中间 receipt/sidecar、Work A 单独 release | 与一个 Package/一次血缘冲突 | 禁止版本和资格化膨胀 | 新 revision 且 CP2/兼容边界重新审查 |
| OUT-072-02 | 真实 qualification/build/canary/tag/release、网络、真实安装或外部消费者写入 | 没有独立 typed authorization | 场景仅定义验证入口 | 后续独立运行、安装与发布授权 |
| OUT-072-03 | 为 checker/recovery 新建 CR、Work、Story 或 CP | 违反 CR=1、Work=2、CP2=1 预算 | 不通过过程膨胀解决问题 | scope/authz 新 revision 或 host 路由 |

## Deferred

| Deferred ID | 来源 | 内容 | 延后原因 | 后续处理 |
|---|---|---|---|---|
| DEF-02 | SGA-02 | legacy reader 的实际退役日期 | 当前已定义量化终止指标，日期仍需迁移观测和后续正式批准 | backlog / follow-up |
| DEF-072-01 | SemVer bootstrap | 将 0.6.1 一次性 token 通用化 | 会降低版本裁决可信度 | 新 CR、独立兼容性评审和用户决定 |

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
| CP2-DQ-02 | implementation | 是否正式冻结 review delta 指定的 read-old/write-new 及量化门槛？ | read-old/write-new：读 v1、只写 canonical v2并保留 provenance/诊断；writer=0、residual=0、ambiguous/misread=100%、连续两次 full-validation v1 observed=0 后才可提议退役 | A. dual-write；B. hard cutover | 推荐兼顾迁移和单一新真相；dual-write 扩大一致性成本；hard cutover 迁移风险最高 | MF-3/MF-4 migration、测试矩阵、回退和维护成本 | formal CP2 已批准；若 reader 无法无歧义归一化则阻断该输入，未达量化门槛不得退役 |
| CP2-DQ-01-072 | scope | 是否冻结一个 0.6.1 Package、两个 planned Work、一次最终 release lineage？ | 冻结；Work A/B 只作为同一 release value 内候选实施单元 | A. 两个中间版本；B. 仅 Work A | 推荐消除双资格化/双血缘；备选会增加成本或留下治理缺口 | 公共 CLI/schema、发布成本、消费者完整性 | 若 Package 边界或兼容面变化，回 requirement-clarification 新 revision |
| CP2-DQ-02-072 | SemVer | 是否接受真实 minor/0.7.0 分类后的一次性、不可复用 0.6.1 bootstrap？ | 接受，且 breaking 永远 BLOCKED | A. 发布 0.7.0；B. 伪装 PATCH（不推荐） | 推荐保留分类真相并满足单版本目标；0.7.0 更保守但偏离目标；PATCH 不可接受 | 兼容边界与版本承诺 | bootstrap 复用、跨版本或 breaking 即阻断并回设计 |
| CP2-DQ-03-072 | admission | 是否批准 P5-0.6.1-release-convergence admission 建议？ | 批准产品建议，Roadmap/Phase 由长期治理 owner 后续更新 | A. 暂缓；B. 不建立 P5 | 推荐把已完成 Roadmap 后的发布收敛交给专门治理；暂缓阻断设计 | 生命周期与 owner 路由 | 状态事实冲突时先由 host/长期治理 owner 核对 |
| CP2-DQ-04-072 | sequencing | 是否接受 measure-only 先于 Work A，Work B 主体在 Work A 后，最终动作仅一次？ | 接受；先测量，再稳定，再汇合 release | A. 立即 hard-gate；B. 并行最终资格化 | 推荐降低未校准阈值风险并防止重复资格化 | 成本门、依赖与发布顺序 | 若 measure-only 不能产出可审计 baseline，停在 hard-gate 之前 |

## MVP 成功判定

- 六个 In Scope 能力均有正向、负向/边界场景和产品 Story。
- P0/P1 产品需求缺口为 0；CR-073 CP2 已于 2026-08-19 批准，后续仍受 CP3/CP4/CP5 与独立运行授权约束。
- 后续 targeted、compatibility、full、contract、migration、projection、fail-closed、recovery 验证全部可由 TEST-MATRIX 回链。

## CR-073 推荐 MVP（CP2 已确认）

In：C0.5 诚实历史对账；init preflight/typed contract/system namespace/additive amend；validation truth/orphan failure recovery；六轮→J1/J2/J3 矩阵；受授权前 source-candidate replay 准备。

Out：伪造 CR-071 PASS、未授权 quant-lab、installed-artifact replay、P7 STATE-CONTRACT/pause-resume/cost hard-gate、过程 Story/代码。
