---
status: draft
current_round: 1
total_rounds: 0
ready_for_design: false
---

## 澄清历史

<!-- 每轮追加，不覆盖历史记录 -->

### 第 1 轮澄清（{date}）

#### 本轮识别的歧义项

| ID | 维度 | 问题描述 | 阻断等级 | 状态 |
|----|------|---------|---------|------|
| Q1 | 目标边界 | ... | BLOCKING | 待回答 |

#### 用户回答记录

| Q-ID | 答复内容 | 记录时间 |
|------|---------|---------|
| Q1 | ... | {date} |

#### 本轮结论

- 剩余 BLOCKING 未决项：N 条
- ready_for_design：false

## 场景发现摘要历史

<!-- 场景发现摘要按时间顺序追加；不得改写上方澄清轮次 -->
<!-- scene-discovery-summaries: begin -->

### 场景发现摘要（{date}）

- USE-CASES 版本：1.0
- 当前状态：draft | confirmed
- 操作模式：create | resume | update

#### 变更摘要

| 类型 | 条目 | 说明 |
|------|------|------|
| 新增 | UC-01 | ... |
| 修改 | UC-02 / P-01 / SM-01 | ... |
| 删除 / 驳回 | （无） | ... |

#### 下一步建议

- 若 `status=confirmed`：可由 meta-pm 以 `process/USE-CASES.md` 为显式输入调用 `requirement-extraction`
- 若 `status=draft`：继续补充遗漏场景或维度后再确认

<!-- scene-discovery-summaries: end -->
