# Meta Flow 0.5.1 回滚方案

## 回滚目标

回滚到已发布的 `v0.5.0` 源码和交付资产。

## 前置检查

1. 运行 Work-init、publication-close 和 Phase metadata 的 inspect 命令。
2. 任一事务处于 `PREPARED`、`APPLYING` 或 `PARTIAL` 时禁止降级；先用 0.5.1 recover 收敛。
3. 确认消费者没有依赖尚未提交的 0.5.1-only metadata successor。

## 回滚动作

1. 从 GitHub 获取 `v0.5.0` exact commit。
2. 重新安装 0.5.0，并核验版本、source OID 和 delivery digest。
3. 重跑 `project check`、`governance check`、`state check`、`work close-inspect` 与 `cr-tracking`。

## 不可破坏的历史

- 不删除 terminal transaction manifest、successor receipt 或 usage event。
- 不改写旧 HANDOFF、base OID、scope、budget 或 result。
- 不用手工 Phase/Project 修改模拟 native recovery。
