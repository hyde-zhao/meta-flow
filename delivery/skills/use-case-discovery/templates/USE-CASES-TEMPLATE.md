---
status: draft | confirmed
version: "1.0"
confirmed_by: ""
confirmed_at: ""
engagement_mode: production | meta-self-dev
scenario_subject_type: target-artifact | implementation-carrier
scenario_subject_id: ""
target_artifact_type: tool | skill | agent | workflow | mixed
governance_mode: direct | review-gated | conditional
review_policy: none | light | strict
delivery_routing:
  mode: meta-flow-delivery | project-readme-contract | proposed-output
  output_root: ""
  source: meta-self-dev | README | docs | user-confirmed
total_use_cases: N
---

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 | 文档处理方式 |
|---|---|---|---|---|
| 1.0 | <YYYY-MM-DD> | meta-pm | 初始场景基线 | 初始化基线 |

## 用户画像（Personas）

| 画像 ID | 角色名称 | 典型背景 | 核心诉求 | 技术水平 |
|---|---|---|---|---|
| P-01 | <角色名> | <1-2 句背景描述> | <想解决的问题> | 初级 / 中级 / 高级 |

## 成功指标（Success Metrics）

| 指标 ID | 指标名称 | 度量方式 | 目标值 |
|---|---|---|---|
| SM-01 | <指标名> | <如何度量> | <目标值，如节省 50% 时间> |

## 明确排除（Out of Scope）

- <不包含的功能或变体 1>
- <不包含的功能或变体 2>

## 治理附录（Governance）

| 字段 | 当前值 | 说明 |
|---|---|---|
| `engagement_mode` | <production / meta-self-dev> | 是否是面向目标产物的生产模式，还是 meta 工作流自我开发模式 |
| `scenario_subject_type` | <target-artifact / implementation-carrier> | 场景主体是目标产物，还是当前实现载体 |
| `scenario_subject_id` | <ptm-tde / meta-flow / ...> | 当前场景真正服务的对象 ID |
| `target_artifact_type` | <tool / skill / agent / workflow / mixed> | 当前场景集的目标交付类型 |
| `governance_mode` | <direct / review-gated / conditional> | 决定下游是否进入评审门禁 |
| `review_policy` | <none / light / strict> | 决定评审强度 |
| `delivery_routing.mode` | <meta-flow-delivery / project-readme-contract / proposed-output> | 交付出口来源；production 不默认写当前仓库 `delivery/` |
| `delivery_routing.output_root` | <路径或空> | 已确认交付输出根目录；未确认时保持空 |
| `delivery_routing.source` | <meta-self-dev / README / docs / user-confirmed> | 输出目录决策依据 |

> 若 `target_artifact_type = mixed`，需在本节补充拆分建议与原因，不得只写结果。

## 头脑风暴与候选方案

> 目标形态、场景主体或交付出口不清时必须填写；简单明确需求可标注“不适用”。

| 候选 ID | 交付形态 / 输出路径 | 适用条件 | 优点 | 风险 / 代价 | 是否主选 |
|---|---|---|---|---|---|
| OPT-01 | <候选方案> | <何时适用> | <优点> | <风险> | 是 / 否 |
| OPT-02 | <候选方案> | <何时适用> | <优点> | <风险> | 是 / 否 |

**分段确认记录**：

| 确认项 | 结论 | 确认来源 |
|---|---|---|
| 场景主体 | <已确认 / 待确认> | <用户回复 / README / docs> |
| 交付出口 | <已确认 / 待确认> | <用户回复 / README / docs> |
| 主选方案 | <OPT-*> | <用户回复> |

## 使用场景列表

> 推荐在“处理逻辑”中优先使用 Given / When / Then 风格；若不适合，可退化为“前置 / 处理 / 结果”。

### UC-01：<场景名称>

| 字段 | 内容 |
|---|---|
| **使用角色** | <谁在用> |
| **触发条件** | <什么情况下触发> |
| **输入** | <用户 / 系统提供什么，含格式说明> |
| **处理逻辑** | <系统执行的步骤，含分支和决策点；推荐 Given / When / Then> |
| **输出/结果** | <用户得到什么，含格式说明> |
| **前置条件** | <使用前需要满足的条件> |
| **排除情况** | <明确不支持的变体> |

**处理流程（文字描述）：**
1. 步骤一：...
2. 步骤二：...
3. 步骤三：...

---

### UC-02：<场景名称>

| 字段 | 内容 |
|---|---|
| **使用角色** | <谁在用> |
| **触发条件** | <什么情况下触发> |
| **输入** | <用户 / 系统提供什么，含格式说明> |
| **处理逻辑** | <系统执行的步骤，含分支和决策点；推荐 Given / When / Then> |
| **输出/结果** | <用户得到什么，含格式说明> |
| **前置条件** | <使用前需要满足的条件> |
| **排除情况** | <明确不支持的变体> |

**处理流程（文字描述）：**
1. 步骤一：...
2. 步骤二：...
3. 步骤三：...

<!-- coverage-checklist: begin -->
## 附录：覆盖自检表

> 本附录是正式兼容结构的一部分；用于记录 8 维覆盖状态，但不改变正文必填字段集。

| 维度 ID | 维度名称 | 状态 | 涉及场景 | 备注 |
|---|---|---|---|---|
| D1 | 用户维度 | 已覆盖 / 已补充 / 不适用 / 待调研 | UC-01 | <补充说明> |
| D2 | 任务维度 | 已覆盖 / 已补充 / 不适用 / 待调研 | UC-01 | <补充说明> |
| D3 | 动机维度 | 已覆盖 / 已补充 / 不适用 / 待调研 | UC-01 | <补充说明> |
| D4 | 时间维度 | 已覆盖 / 已补充 / 不适用 / 待调研 | UC-01 | <补充说明> |
| D5 | 环境维度 | 已覆盖 / 已补充 / 不适用 / 待调研 | UC-01 | <补充说明> |
| D6 | 方式维度 | 已覆盖 / 已补充 / 不适用 / 待调研 | UC-01 | <补充说明> |
| D7 | 异常维度 | 已覆盖 / 已补充 / 不适用 / 待调研 | UC-01 | <补充说明> |
| D8 | 集成维度 | 已覆盖 / 已补充 / 不适用 / 待调研 | UC-01 | <补充说明> |
| Dx | 自定义维度（可选） | 已覆盖 / 已补充 / 不适用 / 待调研 | UC-02 | <仅在会话中临时追加时填写> |
<!-- coverage-checklist: end -->

## 附录：治理变更记录（可选）

| 版本 | 变更字段 | 旧值 | 新值 | 原因 |
|---|---|---|---|---|
| 1.0 | `target_artifact_type` | <空> | <skill> | <首次确认> |
