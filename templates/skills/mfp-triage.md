---
name: mfp-triage
roles: [manager]
trigger: meta-flow 归档中出现待评估 MFP
inputs: [MFP inbox/archive, REQ/架构约束]
outputs: [accepted/rejected/deferred + 设计/直接实现]
read: [improvements/, architecture/]
write: [improvements/]
budget: 按 manager 预算
---

# SKILL mfp-triage

> 适用角色: meta-flow manager
> 触发: 评估 MFP
> 输出: 评估结论与下一步

## 步骤

1. 读 MFP 问题/复现/期望/实际/证据/验收；确认来源项目与 ID（`MFP-<project>-<seq>`）。
2. `mf improve triage <id> --decision accepted|rejected|deferred [--reason] [--next-step design|direct] [--target <版本>]`。
3. 接收：转设计（`design-dispatch`）或工作包（`work-package-plan`）；拒绝/延期：写理由/触发条件。
4. 结论回写来源项目由 maintainer 同步（`mf improve sync`）；manager 不归档。

## 门禁

- 只有 meta-flow maintainer 可归档/同步；生产项目角色不得归档（N3）。
- MFP 不直接变任务；先评估再设计/实现。

## 失败/升级

- 来源信息不足 → 退回记录者补充。
- 跨项目/接口影响 → D1 用户确认。
- 下一责任: designer/worker 或 maintainer（同步）。

## 证据

- ledger `mfp.triaged`；archive index 与生产项目 `state.json`。

## 反模式

- 生产项目角色直接归档；评估不写理由/触发条件。
