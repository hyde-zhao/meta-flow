---
name: decision-point
roles: [manager, worker, designer]
trigger: 工作被不确定项阻塞（需求语义/接口/数据模型/安全/合规）
inputs: [问题/影响/选项/建议/级别]
outputs: [决策点（DEC）+ 暂停/恢复工作包]
read: [工作包, 设计/规格]
write: [工作包 bundle]
budget: 任务包
---

# SKILL decision-point

> 适用角色: manager/worker/designer
> 触发: 阻塞需要拍板
> 输出: 决策点与决策记录

## 步骤

1. `mf work decision <wp> --problem ... --impact ... --option ... --recommendation ... --level D0-D3 --decision-owner user|manager`。
2. D0/D1 升级用户；D2 manager 决定；D3 自动并审计。
3. 决策后 `mf work decision <wp> --decision-id <id> --decision ... --decided-by ...` 恢复。
4. 决策结果写回设计/规格/工作包，不在对话口头闭环。

## 门禁

- 决策点必须有问题/影响/选项/建议/级别/owner。
- 不把决策藏进实现任务；D0/D1 不得自行决定。

## 失败/升级

- 决策仍不明确 → 用户门禁（D0）。
- 下一责任: 提出者（恢复执行）。

## 证据

- WORK-PACKAGE 决策任务、ledger `work_package.decision_*`。

## 反模式

- 只写“需要确认”；决策后不写回文档。
