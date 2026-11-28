---
name: bug-fix
roles: [worker]
trigger: 任务/工作包关联 external BUG 修复
inputs: [BUG 包（复现/期望/实际）, 任务 allowed_paths]
outputs: [修复/自验证据/验证请求]
read: [任务关联 BUG, 子项目源码]
write: [allowed_paths, 任务 bundle]
budget: 任务包
---

# SKILL bug-fix

> 适用角色: worker
> 触发: 修复 manager 分派的 external BUG
> 输出: 修复 + 自验证据

## 步骤

1. `mf bug show <id>`（仅活动任务关联 BUG）读复现/期望/实际。
2. 在任务 allowed_paths 内修复；先写失败用例再修复。
3. `mf bug fix <id> --task <task> --fixed` 标记 fixed；自验 L1。
4. 交独立验证（critical/major 必须独立 worker）：`mf bug verify`。
5. external 关闭由 manager 与用户确认（`--confirmed-by --note`）；worker 不关闭。

## 门禁

- 不直接改未授权文件；修复超原工作包/规格范围 → 决策点/升级。
- 不得自验自关；不得代替用户确认。

## 失败/升级

- 复现失败/范围扩大 → manager 分诊。
- 同子项目内部缺陷走 `verification-bug`。
- 下一责任: verifier/manager。

## 证据

- 修复 diff、失败/通过用例、命令输出、ledger `bug.fixed`。

## 反模式

- 无失败用例直接改代码；伪造验证；绕过用户确认关闭。
