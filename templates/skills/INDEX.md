# 技能索引（Skills INDEX）

> 提示词只定义身份/权限/工作区；活动步骤见 skill。`mf skill list` 读取
> `contract/skills/`、子项目 `skills/` 与 `templates/skills/`；`mf skill validate` 校验结构。
> 规则：每个 skill ≤1 页；不改权限；输出写文件/ledger；结束明确 next_owner。

| skill | 角色 | 触发 | 主要输出 |
|---|---|---|---|
| req-intake | manager | 用户提出需求 | REQ 草案 |
| req-triage | manager | 评估 REQ | accepted/rejected/deferred + 下一步 |
| mfp-triage | manager | 评估 MFP | 评估结论/设计或实现 |
| design-intake | designer | 接收设计工作包 | 设计计划/问题清单 |
| spec-authoring | designer | 编写 SPEC | SPEC/映射/验收判定 |
| work-package-plan | manager | 设计验收后规划 | 工作包/任务/决策/验证 |
| work-package-execution | worker | 执行工作包 | 实现/证据/交接 |
| self-verification | worker/designer | 提交前自验 | L1 证据 |
| verification | worker/designer | 独立验证 | 验证结论 |
| verification-bug | worker | 同子项目验证缺陷 | BUG 记录/viewer 关闭 |
| bug-fix | worker | external BUG 修复 | 修复/证据 |
| cross-project-verification | designer | 跨项目接口/E2E | 验证记录 |
| release | manager | P5 发布 | 发布证据/用户门禁 |
| mfp-archive | maintainer | 归档 MFP | archive/index.json |
| mfp-sync | maintainer | 同步 resolution | 生产项目 state.json |
| decision-point | manager/worker/designer | 阻塞拍板 | 决策点/决策记录 |
| handoff | 全部 | 提交/交接 | dev-record/handoff |

## 分层

- 角色提示词（agents）：身份/权限/工作区/活动索引。
- skill（本目录）：步骤/输入输出/门禁/失败/证据/反模式。
- standards：项目级规则；CLI/guard：强制边界。
