---
name: cross-project-verification
roles: [designer]
trigger: 跨子项目接口/E2E/工作包验证
inputs: [工作包/接口契约/SPEC, 验证范围]
outputs: [跨项目验证记录与结论]
read: [contract 设计/规格, 子项目接口（只读）]
write: [验证任务 bundle 流程文件]
budget: 验证任务包
---

# SKILL cross-project-verification

> 适用角色: designer
> 触发: 跨子项目验收/接口/E2E
> 输出: 验证记录；通过后交 manager 最终验收

## 步骤

1. 确认接口契约/SPEC/工作包范围与参与子项目。
2. 在临时工作区复现 E2E/接口检查；记录命令、期望、实际、退出码。
3. 失败：记录接口/契约问题；需要决策 → 决策点；否则返回对应子项目 worker。
4. 通过：写验证记录，交 manager 最终验收。
5. 不写生产源码；不代替 worker 修复。

## 门禁

- 跨子项目任务只按 scope 只读/测试，写入一律拒绝。
- 证据缺失不得 PASS；PASS_WITH_RISK 写风险与接受人。

## 失败/升级

- 规格/接口冲突 → D1 用户确认。
- 跨项目缺陷 → external BUG（manager 分诊）。
- 下一责任: manager（最终验收）或子项目 worker（返工）。

## 证据

- E2E/接口命令输出、验证记录、ledger。

## 反模式

- 用单子项目验证冒充跨项目验证；修改实现或验收标准。
