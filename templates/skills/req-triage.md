---
name: req-triage
roles: [manager]
trigger: REQ 草案待评估
inputs: [REQ 草案, 路标/版本计划, 资源约束]
outputs: [accepted/rejected/deferred + 下一步（设计/直接开发）]
read: [requirements/, roadmap/]
write: [requirements/REQUIREMENTS.yaml]
budget: 按 manager 预算
---

# SKILL req-triage

> 适用角色: manager
> 触发: 评估 REQ
> 输出: 状态与下一步

## 步骤

1. 检查范围/验收是否可判定；不满足 DoR 退回补充。
2. `mf req triage REQ-xxxx --decision accepted --next-step design|direct`（或 rejected/deferred + --reason）。
3. 需要设计：派 designer（`mf design create`/design 任务）；直接开发：创建/加入工作包。
4. 记录理由、影响、通知用户。

## 门禁

- 拒绝/延期必须写理由；不得留在对话。
- 接收必须明确下一步；无 SPEC 的 REQ 不进入实现。

## 失败/升级

- 需求语义/范围冲突 → D0/D1 用户确认。
- 下一责任: designer（设计）或 worker（工作包）。

## 证据

- ledger `req.triaged`；REQ assessment 字段。

## 反模式

- 只改状态不写下一步；把决策藏在实现任务里。
