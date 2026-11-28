---
name: design-intake
roles: [designer]
trigger: manager 派发设计工作包
inputs: [设计工作包, REQ/MFP, 约束]
outputs: [设计计划, 问题清单, 范围确认]
read: ["requirements/", "architecture/", "roadmap/"]
write: ["roadmap/R{n}/phases/P2/design/"]
budget: 按任务包
---

# SKILL design-intake

> 适用角色: designer
> 触发: 接收设计工作包
> 输出: 设计计划与问题清单

## 步骤

1. `mf task prompt <id>` 确认 design 任务与 allowed_paths。
2. 读 REQ/MFP/约束；列出未知项、冲突与需决策问题。
3. 输出设计计划（信息流/架构/模块/接口/规格映射/预研），确认范围。
4. 有阻塞 → 决策点/ BLOCKED；不写生产源码。

## 门禁

- 设计输入不完整不猜；D0/D1 升级用户/manager。
- 不写源码、不改验收标准。

## 失败/升级

- 范围冲突 → manager；需求语义 → D0 用户。
- 下一责任: designer（spec-authoring）。

## 证据

- 设计计划、问题清单、ledger `design.package_created`。

## 反模式

- 直接给实现方案；跳过问题清单；manager 代写设计正文。
