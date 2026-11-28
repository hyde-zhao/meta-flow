---
name: verification-bug
roles: [worker]
trigger: 同子项目验证/工作包执行中发现缺陷
inputs: [发现场景/复现/期望/实际, 子项目]
outputs: [verification BUG 记录 + 修复 + viewer 关闭]
read: [本子项目 BUG, 任务/工作包]
write: [本子项目 allowed_paths, 任务 bundle]
budget: 任务包
---

# SKILL verification-bug

> 适用角色: 同子项目 worker/viewer
> 触发: 实施期验证发现缺陷（REQ-0018 AC6）
> 输出: BUG 记录、修复、非修复者 viewer 关闭

## 步骤

1. `mf bug add --flow verification --subproject <sub> --title ... --steps ... --expected ... --actual ...`。
2. 同子项目 worker 修复：`mf bug fix <id> --task ... --fixed`。
3. 非修复者 viewer 复验：`mf bug verify <id> --by <viewer> --evidence ...`。
4. viewer 关闭：`mf bug close <id> --verification ... --by <viewer>`；`closure_type=viewer`。
5. manager/用户不参与；所有状态写 ledger。

## 门禁

- 仅同一子项目；`scope=same_subproject`。
- 修复者不得验证/关闭自己的修复（自验自关拒绝）。
- 跨子项目/接口/外部可见/安全/需求级 → `mf bug escalate` 升级 external。

## 失败/升级

- 无独立 viewer → manager/designer 指定同子项目验证者。
- 修复超范围 → 升级 external/决策点。
- 下一责任: 修复 worker（不通过）或关闭记录（通过）。

## 证据

- BUG 记录、复验证据、ledger `bug.verified/bug.closed`。

## 反模式

- 用 peer flow 关闭跨项目缺陷；自我验证；把 external BUG 当 verification 处理。
