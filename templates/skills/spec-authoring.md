---
name: spec-authoring
roles: [designer]
trigger: 设计输出规格（SPEC）
inputs: [REQ/MFP, 模块/接口设计, 验收场景]
outputs: [SPEC 文档（P2 过程目录）]
read: ["architecture/", "requirements/", "roadmap/R{n}/phases/P2/"]
write: ["roadmap/R{n}/phases/P2/specs/", "roadmap/R{n}/phases/P2/design/"]
budget: 按任务包
---

# SKILL spec-authoring

> 适用角色: designer
> 触发: 为 REQ/MFP 编写 SPEC
> 输出: SPEC + 映射 + 可测试场景

## 步骤

1. 从 REQ 验收场景推导可测试需求（Given-When-Then）；非目标写清。
2. SPEC 写 R{编号} 需求、接口/数据、验收判定；不写验证计划/测试命令。
3. 输出 REQ/MFP→SPEC→子项目/模块映射；无孤儿。
4. `mf design create` 记录设计包；`mf design accept` 由 manager 验收。
5. 规格冻结后实施不得静默修改；变更走 CHG。

## 门禁

- 每条 REQ 至少一个 SPEC；跨模块规格必须有独立 verify 任务。
- SPEC 位于 `roadmap/R{n}/phases/P2/specs/`；legacy `specs/` 只兼容读取。

## 失败/升级

- 需求冲突/接口不决 → D1 用户确认。
- 下一责任: manager（设计验收）或 worker（工作包）。

## 证据

- SPEC、DP、映射表、ledger `design.accepted`。

## 反模式

- 在 architecture/ 长期目录写 SPEC；规格含实现细节；无验收判定。
