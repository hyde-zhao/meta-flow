---
name: verification
roles: [worker, designer]
trigger: 独立验证任务/工作包最终验证
inputs: [验证任务包, 验收项, 负向矩阵, 实现证据]
outputs: [验证记录与结论]
read: [review_scope, 目标 bundle]
write: [验证任务 bundle 流程文件]
budget: 验证任务包
---

# SKILL verification

> 适用角色: 非实现者 worker / designer（跨项目）
> 触发: 验证
> 输出: PASS/PASS_WITH_RISK/NEEDS_REWORK/BLOCKED

## 步骤

1. 确认非实现者；读任务包/验收/负向矩阵。
2. 执行正向/负向/边界检查；记录命令、期望、实际、退出码。
3. 安全任务复现负向矩阵全部命令；缺证据不得 PASS。
4. 结论四值；失败列必须整改项（ID/文件/行/要求/验收方法），用人话写原因/风险/影响/期望。
5. 写验证记录/交接；明确下一责任（worker 返工/决策点/manager）。

## 门禁

- 不修改实现/验收标准；只读验证范围。
- 不评审自己参与的任务；PASS_WITH_RISK 写风险与接受人。

## 失败/升级

- 同子项目验证期缺陷 → `verification-bug`（viewer 关闭）。
- 跨项目/接口/外部可见/安全/需求级 → 升级 external BUG。
- 下一责任: 实现 worker 直接返工（NEEDS_REWORK）。

## 证据

- 验证记录、命令输出、负向矩阵、ledger。

## 反模式

- 高层条目代替命令证据；自验自关；PASS 无证据。
