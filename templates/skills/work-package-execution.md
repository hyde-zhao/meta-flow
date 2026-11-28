---
name: work-package-execution
roles: [worker]
trigger: 接收工作包/任务
inputs: [WORK-PACKAGE.yaml, SPEC, allowed_paths]
outputs: [实现/证据/dev-record/handoff]
read: [工作包, SPEC, 子项目源码]
write: [allowed_paths, 任务 bundle 流程文件]
budget: 任务包 budget
---

# SKILL work-package-execution

> 适用角色: worker
> 触发: 执行工作包任务
> 输出: 可独立验证增量 + 证据

## 步骤

1. `mf work show <wp>` 读上下文/任务/验收；`mf task prompt <id>` 确认责任（有任务卡时）。
2. `mf work start <wp>` / `mf task start <id>` 取得范围；只写 allowed_paths。
3. 按验收实现；先写负例/边界，再做最小实现切片。
4. 自验 L1（命令、退出码、输出）；需要独立验证时说明场景。
5. 写 dev-record/handoff/evidence；`mf task submit`。

## 门禁

- 缺目标/输入/交付物/验收/路径/依赖 → BLOCKED，不猜。
- 不跨子项目/其他 R；不自验收；不声称 L2/L3 通过。

## 失败/升级

- D0/D1 写 BLOCKED/决策点；D2 记关键决策；D3 留提交说明。
- 下一责任: verifier/manager。

## 证据

- dev-record、handoff、evidence（含未跟踪新增测试文件）。

## 反模式

- 扩范围；改验收标准；用 shell 绕过 guard/读预算。
