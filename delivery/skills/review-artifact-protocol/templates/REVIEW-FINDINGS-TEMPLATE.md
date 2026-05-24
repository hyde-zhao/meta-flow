---
artifact: ""
reviewer: ""
lane: ""
input_type: "advisor_formation | post_hld_review | review_findings"
round: 1
status: draft
governance_mode: review-gated
---

# Review Findings

## 1. 审查范围

- 目标对象：`<path>`
- 审查目标：`<coverage / contract / architecture / quality / readability>`
- 审查依据：`<rule refs>`

## 2. Findings

### Advisor Table（CP3 方案形成输入适用）

> 仅当 `input_type=advisor_formation` 时填写；HLD 后评审意见不得倒填到本表。

| Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch |
|---|---|---|---|---|---|
| `<候选>` | `<优势>` | `<代价>` | `<范围 / 模块 / 数据 / 安全 / 验证 / 文档>` | `<推荐 / 条件推荐 / 不推荐>` | `<假设与切换条件>` |

<!-- findings-table -->

| ID | Severity | Rule Ref | Evidence | Impact | Suggestion | Anchor |
|----|----------|----------|----------|--------|------------|--------|
| F-001 | 严重/一般/轻微 | `rule-id` | `事实证据` | `影响范围` | `修改建议` | `#section-or-line` |

## 3. 汇总结论

- blocking_count: 0
- required_count: 0
- optional_count: 0
- recommended_next_action: `revise-and-resubmit / proceed / escalate`
- decision_impact: `<对用户决策的影响，供 Decision Brief 聚合>`
- trade_off_note: `<本 lane 看到的主要优劣取舍>`

## 4. 待确认项

- `<如无则写 None>`
