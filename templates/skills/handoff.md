---
name: handoff
roles: [manager, designer, worker, maintainer]
trigger: 任务/工作包结束或阻塞
inputs: [实现/验证/决策结果]
outputs: [dev-record, handoff, 下一责任]
read: [任务 bundle]
write: [任务 bundle 流程文件]
budget: 任务包
---

# SKILL handoff

> 适用角色: 全部角色
> 触发: 提交/阻塞/交接
> 输出: 可复核的交接

## 步骤

1. dev-record 写实现、测试、关键决策（D2）、残余风险。
2. handoff 写结论、变更、证据、未决/阻塞、下一步与下一责任 agent。
3. 阻塞：写最小阻塞证据与 `needs: acceptance|bug|mfp|chg` 标注。
4. 运行 `mf task prompt <id>` 确认 next_owner；`mf task submit`。

## 门禁

- 结论先行、证据可复核；未记录的风险不得留在对话。
- 实现者不自验收；评审结论只作 manager 决策输入。

## 失败/升级

- 工具缺口 → 本地 MFP（`mf improve new --local`）并写入交接“改进包”。
- 下一责任: manager/worker/reviewer。

## 证据

- dev-record、handoff、evidence 索引。

## 反模式

- 交接只写“完成”；遗漏失败/风险；在对话里闭环问题。
