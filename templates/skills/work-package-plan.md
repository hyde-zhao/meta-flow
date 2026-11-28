---
name: work-package-plan
roles: [manager]
trigger: 设计验收通过，进入实施
inputs: [DP/SPEC, REQ/MFP, 接口]
outputs: [每子项目工作包（上下文/任务/决策/验证）]
read: ["roadmap/R{n}/phases/P2/", "architecture/"]
write: ["roadmap/R{n}/phases/P3/work-packages/"]
budget: 按 manager 预算
---

# SKILL work-package-plan

> 适用角色: manager
> 触发: 规划实施工作包（REQ-0019/CHG-0005）
> 输出: 工作包与任务区间

## 步骤

1. 每子项目每个设计周期创建一个工作包：
   `mf work create --subproject <sub> --requirement ... --spec ... --allowed-path ... --acceptance ...`
2. 仅在“需要人工决策/必要独立验证”时 `mf work task` 拆分；连续实现用一个任务。
3. 决策用 `mf work decision`（问题/影响/选项/建议/级别/owner），阻塞工作包。
4. 默认不按任务生成 review 任务；工作包完成做子项目最终验证，再 `mf work accept`。
5. 必要独立验证场景：安全/角色/guard/权限、跨子项目接口/E2E、用户可见/UAT、高风险不可逆、manager/designer 判定必要。

## 门禁

- 工作包必须有 DP/SPEC 引用、allowed_paths、预算、验收。
- 设计未验收不得建实现工作包；任务卡只用于独立验证/决策/跨项目/审计。

## 失败/升级

- 验证失败：reviewer 用人话写原因/风险/期望，实现 worker 直接返工。
- 范围外事项 → CHG/BUG/MFP/新卡，不阻塞范围内返工。
- 下一责任: worker（执行）或 manager（验收）。

## 证据

- WORK-PACKAGE.yaml、ledger `work_package.*`。

## 反模式

- 每文件/命令一个任务包；把决策藏进实现；按任务机械开 review。
