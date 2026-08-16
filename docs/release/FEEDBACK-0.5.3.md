# Meta Flow 0.5.3 发布后观察

发布后记录以下事实，不自动触发 mutation：

- targeted/compatibility/full receipt 的 source、profile、command、environment、runner、evidence 与 provenance identity；
- 三个已接受基线 failure ID 是否保持不变，任何新 failure ID 立即按 regression 处理；
- scope-amend successor/invalidation、preflight/apply graph parity 与 unknown-leaf deny 频率；
- receipt reuse 的拒绝率、七维 taxonomy 边界样本与 comparison epoch reset；
- observation store 的 hash-chain/CAS 恢复、容量阈值和 consecutive comparable snapshots；
- projection recovery 是否只解除 missing-evidence blocker，是否出现越权或死锁；
- provider v8 与 artifact receipt 是否持续 CURRENT/exact。

后续独立事项：调查三个残余 full-suite 基线失败；真实 correction/cutover 仅在 fresh zero-write plan 与独立授权下执行；reader retirement 只有四项门槛有机器证据后才可提议。
