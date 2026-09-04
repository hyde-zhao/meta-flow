---
status: release_candidate
version: "0.6.5"
rollback_target: "0.6.3"
---

# Meta Flow 0.6.5 Rollback

## 回滚原则

0.6.5 的可执行资产回滚目标是公开版本 0.6.3。0.6.4 不存在，不能作为回滚目标。回滚不删除或改写 Work、CR、authorization、receipt、transaction manifest 或 append-only evidence。

## 触发条件

- 安装后 provider identity 不是 READY/CURRENT；
- V1 G2 被误读为轻量 G2；
- 未经用户显式选择进入 G3；
- pending gate 越过缺失阶段或旧 approval 被复用；
- publication operation 三档命名空间受治理 G3 污染；
- wheel、sdist、receipt、sidecar 或远端摘要漂移。

## 回滚步骤

1. 停止新的 0.6.5 安装和发布动作，保留失败日志与资产摘要。
2. 从 v0.6.3 GitHub Release 下载 exact wheel、receipt 与 sidecar 并校验摘要。
3. 在新隔离环境安装 0.6.3；不要覆盖原环境后再猜测回滚结果。
4. 将调用入口切换到已验证的 0.6.3 环境。
5. 验证 `meta-flow version`、provider identity 和关键只读命令。
6. 将失败分流为 0.6.5 修复；不得删除 v0.6.5 tag 或强推历史。

已由 0.6.5 写出的 V2 G2/G3 对象不应交给不了解 V2 schema 的旧版本执行写操作；回滚后仅允许只读检查或显式兼容恢复。
