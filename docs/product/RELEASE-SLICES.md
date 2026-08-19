---
status: confirmed
version: "1.2"
source_change: "CR-071 + CR-072"
formal_cp2_status: approved
confirmed_by: "user"
confirmed_at: "2026-08-18T08:02:17Z"
formal_cp2_approval_ref: "process/state/GATE-LEDGER.ndjson#GATE-CR072-CP2-APPROVED-20260818-V1"
---

# CR-071 Release Slices

## 修订记录

| 版本 | 日期 | 变更要点 |
|---|---|---|
| 1.0 | 2026-08-15 | 建立 RS-01～RS-03 产品价值切片 |
| 1.1 | 2026-08-15 | 吸收 CP2 revision 2 的 enabling prerequisite、量化门槛和恢复出口 |
| 1.2 | 2026-08-18 | CR-072 仅保留一个 0.6.1 外部发布；内部 Wave 不构成 release slice | 保留 CR-071 RS-01～03；不生成中间版本 |

## 切片列表

| Slice ID | 名称 | 用户价值 | 包含 Story | 前置依赖 | 验证入口 | 发布风险 |
|---|---|---|---|---|---|---|
| RS-01 | Work 生命周期安全 | preflight/apply 共享判断源，并以可审计 revision 修订 scope | ST-MF1, ST-N-MF1, ST-MF2, ST-N-MF2 | BL-001 revision>1 admission；CP3 shared validation core invariant | SCN-MF1-01～SCN-MF2-03；decision parity + mutation=0 + fail-closed | 校验规则重复；supersession admission 漏检；partial revision |
| RS-02 | 公共合同清晰迁移 | 引用和 full regression policy 不再因旧字段/前缀被误读，reader 退役有量化依据 | ST-MF3, ST-N-MF3, ST-MF4, ST-N-MF4 | formal CP2 冻结 read-old/write-new；CP3 canonical schema/field ADR | SCN-MF3-01～SCN-MF4-03；writer=0、residual=0、ambiguous/misread=100%、two-snapshot observed=0 | v1 reader 歧义；dual truth；required full 被跳过 |
| RS-03 | 证据与投影可信 | 复用语义稳定验证层，并让缺证失败在补证后自动恢复 | ST-MF5, ST-N-MF5, ST-MF6, ST-N-MF6 | RS-02 的 canonical identity/provenance vocabulary | SCN-MF5-01～SCN-MF6-03；false reject=0、safety drift reject=100%、one reprojection convergence | 陈旧 PASS 复用；等价误拒；unknown failure 被伪装健康；手改派生状态 |
| RS-072-01 | 0.6.1 单一 Release Package | 一个版本内完成 Work A 稳定化/消费者完整性与 Work B 编译器/成本/发布机器门，并只在最终点发布一次 | ST-072-PLAN～ST-072-CONSUMER 及负向 Story | CP2 scope 冻结、后续 CP3/CP5、两 Work 验证和 aggregate evidence | SCN-072-01～12；最终顺序、qualification-once、clean-home canary | 双血缘、freeze drift、bootstrap 重用、过程膨胀 |

## 切片顺序理由

| Slice ID | 为什么先 / 后做 | 不这样切的代价 |
|---|---|---|
| RS-01 | 先建立安全创建/修订边界，后续 schema 与验证工作才能减少重开 Work | 仍会在后续切片因 scope 不足而取消执行容器 |
| RS-02 | 再统一 typed ref 和 validation policy，为 receipt/projection 提供 canonical identity | MF-5/MF-6 会继续依赖含歧义的旧合同 |
| RS-03 | 最后使用稳定合同优化复用与失败可见性 | 过早复用可能放大陈旧证据或错误健康投影 |
| RS-072-01 / Wave-1 | measure-only baseline，再由 Work A 稳定化/消费者完整性建立可汇合基础 | 过早 hard-gate 或 Work A 单独发布会产生无校准阈值或中间血缘 |
| RS-072-01 / Wave-2 | Work B 编译器/closure/cost/SemVer/release-order 在同一 Package 内完成 | 与 Work A 拆版本会重复资格化和 canary |
| RS-072-01 / Wave-3 | 仅在两 Work 验证后一次执行 freeze→decision→fingerprint→qualification→build→canary→tag/release | 倒序或重复动作会导致 drift 与不可审计 release |

## 发布门禁提示

- 每个切片都必须独立验证安全不变量；单切片失败只回当前切片，不得掩盖为 baseline limitation。
- legacy 兼容策略与量化门槛已由 formal CP2 冻结，具体 schema/字段候选由 CP3 决定。
- CP4 必须分解 `meta_flow/workflow/cr_cli.py`、`meta_flow/workflow/cr_index.py`、`meta_flow/work/model.py`、`meta_flow/state/formal_projection.py`，并盘点对应四个测试文件；这不是当前实现/验证声明。
- 本文件的“Release Slice”只表示产品价值切片，不授权 commit、publish、release、真实安装或生产写。
- `RS-072-01` 是唯一可发布切片；Wave-1～3 是内部实施/验证顺序，绝不构成 `0.6.1-stabilization`、`0.7.0` 或中间 receipt/sidecar。
