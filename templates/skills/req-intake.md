---
name: req-intake
roles: [manager]
trigger: 用户提出需求/口头描述/文档输入
inputs: [用户描述, 相关 MFP/BUG, 项目约束]
outputs: [REQ 草案（source/priority/scope/acceptance）]
read: [requirements/, 当前 PLAN, ROADMAP]
write: [requirements/REQ-*.md, requirements/REQUIREMENTS.yaml]
budget: 按 manager 预算
---

# SKILL req-intake

> 适用角色: manager
> 触发: 用户提出需求
> 输出: REQ 草案（状态 proposed）

## 步骤

1. 复述问题与用户结果，确认不是实现细节。
2. `mf req add --title ... --acceptance ...` 记录来源、优先级、范围/非目标、验收（正常/异常/边界）。
3. 关联 MFP/BUG/历史 REQ；标注未知项。
4. 交 `req-triage` 评估；不直接承诺开发。

## 门禁

- 缺可验证验收 → 不进入 accepted（`mf req validate`）。
- 每条 REQ 至少一个 SPEC 或明确“直接开发”理由。

## 失败/升级

- 需求语义不清 → D0 用户确认。
- 跨项目/架构影响 → D1 用户确认。
- 下一责任: manager（triage）。

## 证据

- REQ 文档、`mf req trace`、ledger `req.add`。

## 反模式

- 把实现方案当需求；不记录来源；口头承诺开发。
