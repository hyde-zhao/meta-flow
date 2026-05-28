---
artifact: ""
round: 1
status: draft
decision: pending
blocking_count: 0
required_count: 0
optional_count: 0
---

# Review Summary

## 1. 输入清单

- findings_files:
  - `<review-findings-file>.md`

## 2. 严重度汇总

| Severity | Count | Owner |
|----------|-------|-------|
| 严重 | 0 | `meta-po` |
| 一般 | 0 | `meta-po` |
| 轻微 | 0 | `meta-po` |

## 3. 决策

- decision: `proceed / revise / escalate`
- rationale: `<聚合结论>`
- next_checkpoint: `<if any>`

### CP3 Advisor Summary（适用时填写）

| Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch |
|---|---|---|---|---|---|
| `<候选>` | `<优势>` | `<代价>` | `<范围 / 模块 / 数据 / 安全 / 验证 / 文档>` | `<推荐 / 条件推荐 / 不推荐>` | `<假设与切换条件>` |

| 输入类型 | 来源 lane | 进入方案形成 | 进入 HLD 后评审 | 处理结果 |
|---|---|---|---|---|
| advisor_formation / post_hld_review | `<lane>` | yes / no | yes / no | adopted / deferred / rejected / fixed / waived |

## 4. Decision Brief 输入

| 字段 | 内容 |
|---|---|
| 推荐决策 | `<建议用户选择 approve / 修改 / reject 及理由>` |
| 备选方案 | `<至少 1 个可执行备选，优先 2 个；若业务上只有 1 个候选，补充治理备选>` |
| 影响维度 | `<用户价值 / 实现复杂度 / 可验证性 / 维护成本 / 平台兼容 / 安全权限 / 交付影响>` |
| 优劣分析 | `<各候选方案主要优势和代价>` |
| 风险与回退 | `<风险等级、接受条件、回退点>` |
| 用户需决策事项 | `<本轮必须由用户决定的事项>` |

## 5. 后续动作

1. `<action>`
