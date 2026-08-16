---
status: draft
version: "1.1"
source_change: "CR-071"
formal_cp2_status: pending
---

# CR-071 Release Slices

## 修订记录

| 版本 | 日期 | 变更要点 |
|---|---|---|
| 1.0 | 2026-08-15 | 建立 RS-01～RS-03 产品价值切片 |
| 1.1 | 2026-08-15 | 吸收 CP2 revision 2 的 enabling prerequisite、量化门槛和恢复出口 |

## 切片列表

| Slice ID | 名称 | 用户价值 | 包含 Story | 前置依赖 | 验证入口 | 发布风险 |
|---|---|---|---|---|---|---|
| RS-01 | Work 生命周期安全 | preflight/apply 共享判断源，并以可审计 revision 修订 scope | ST-MF1, ST-N-MF1, ST-MF2, ST-N-MF2 | BL-001 revision>1 admission；CP3 shared validation core invariant | SCN-MF1-01～SCN-MF2-03；decision parity + mutation=0 + fail-closed | 校验规则重复；supersession admission 漏检；partial revision |
| RS-02 | 公共合同清晰迁移 | 引用和 full regression policy 不再因旧字段/前缀被误读，reader 退役有量化依据 | ST-MF3, ST-N-MF3, ST-MF4, ST-N-MF4 | formal CP2 冻结 read-old/write-new；CP3 canonical schema/field ADR | SCN-MF3-01～SCN-MF4-03；writer=0、residual=0、ambiguous/misread=100%、two-snapshot observed=0 | v1 reader 歧义；dual truth；required full 被跳过 |
| RS-03 | 证据与投影可信 | 复用语义稳定验证层，并让缺证失败在补证后自动恢复 | ST-MF5, ST-N-MF5, ST-MF6, ST-N-MF6 | RS-02 的 canonical identity/provenance vocabulary | SCN-MF5-01～SCN-MF6-03；false reject=0、safety drift reject=100%、one reprojection convergence | 陈旧 PASS 复用；等价误拒；unknown failure 被伪装健康；手改派生状态 |

## 切片顺序理由

| Slice ID | 为什么先 / 后做 | 不这样切的代价 |
|---|---|---|
| RS-01 | 先建立安全创建/修订边界，后续 schema 与验证工作才能减少重开 Work | 仍会在后续切片因 scope 不足而取消执行容器 |
| RS-02 | 再统一 typed ref 和 validation policy，为 receipt/projection 提供 canonical identity | MF-5/MF-6 会继续依赖含歧义的旧合同 |
| RS-03 | 最后使用稳定合同优化复用与失败可见性 | 过早复用可能放大陈旧证据或错误健康投影 |

## 发布门禁提示

- 每个切片都必须独立验证安全不变量；单切片失败只回当前切片，不得掩盖为 baseline limitation。
- legacy 兼容策略与量化门槛必须先由 formal CP2 冻结，具体 schema/字段候选由 CP3 决定。
- CP4 必须分解 `meta_flow/workflow/cr_cli.py`、`meta_flow/workflow/cr_index.py`、`meta_flow/work/model.py`、`meta_flow/state/formal_projection.py`，并盘点对应四个测试文件；这不是当前实现/验证声明。
- 本文件的“Release Slice”只表示产品价值切片，不授权 commit、publish、release、真实安装或生产写。
