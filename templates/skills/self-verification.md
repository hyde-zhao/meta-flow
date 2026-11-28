---
name: self-verification
roles: [worker, designer]
trigger: 完成实现后自验 L1
inputs: [任务验收项, 实现变更]
outputs: [L1 证据（命令/期望/实际/退出码）]
read: [任务包, allowed_paths]
write: [任务 bundle evidence/]
budget: 任务包
---

# SKILL self-verification

> 适用角色: 实现者
> 触发: 提交前自验 L1
> 输出: L1 证据

## 步骤

1. 逐条验收项执行定向测试（targeted → compatibility → full）。
2. 记录命令、期望、实际、退出码；失败保留日志。
3. 安全任务跑负向矩阵并记录正/负例表。
4. 结果写入 evidence/ 与 dev-record；不声称 L2/L3 通过。

## 门禁

- 证据缺失不得提交 PASS。
- 自验不等于独立验证/验收。

## 失败/升级

- 失败修复后重跑；无法复现/环境异常 → BLOCKED 并记录。

## 证据

- evidence/ 日志、pytest/ruff/doctor 输出。

## 反模式

- 用高层结论代替命令输出；只跑全量不跑定向；伪造通过。
