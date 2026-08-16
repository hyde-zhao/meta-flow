---
status: draft
version: "1.1"
source_change: "CR-071"
---

# CR-071 Backlog

## 修订记录

| 版本 | 日期 | 变更要点 |
|---|---|---|
| 1.0 | 2026-08-15 | 建立 BL-001～BL-003 |
| 1.1 | 2026-08-15 | BL-001 从 deferred candidate 重分类为 MF-2 enabling prerequisite；收窄 BL-002/003 |

| Item ID | 类型 | 来源 | 内容 | 当前状态 | 延后原因 | 重启条件 |
|---|---|---|---|---|---|---|
| BL-001 | enabling_prerequisite | MF-2 / CP2 revision 2 REV-01 | terminal predecessor inventory 接入 revision>1 legal supersession admission | current-scope-required | 不是延后项；必须先闭合 MF-2 实现与 E2E admission，且不得新增 MF-7 | predecessor/inventory 被确定接纳，合法/非法 revision>1 fixture 分别通过/fail closed |
| BL-002 | follow-up | SGA-02 / CP2-DQ-02 | legacy reader 的实际退役日期 | candidate | 当前基线已规定 writer=0、residual=0、ambiguous/misread=100%、连续两个 full-validation 快照 v1 observed=0；只剩日期需后续决定 | 四项门槛达标且后续正式 gate 批准具体日期 |
| BL-003 | enhancement | UC-VALIDATION-REUSE | 在 canonical semantic-equivalence 安全门槛之外进一步优化真实运行成本/性能 | candidate | 当前 MF-5 已要求等价 fixture 误拒=0、安全相关非等价漂移拒绝=100%；本项不得放宽安全阈值 | CP7/CP8 有稳定性能与成本证据，且安全阈值持续满足 |

## 台账边界

`BACKLOG.md` 是产品规划 backlog，不是 CP8 follow-up tracking 正式台账。本阶段不创建正式后续 CR、不改 CR index 或 ledger；如未来需要正式跟踪，必须由后续 gate 按原生流程分流。
