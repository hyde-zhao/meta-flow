---
status: draft
version: "1.0"
---

# Dependency Map

## 依赖关系

| From | To | 依赖类型 | 允许方向 | 原因 | 验证 / 监控 |
|---|---|---|---|---|---|
| FEAT-01 | FEAT-02 | read / write / event / runtime / file-conflict | allowed / forbidden | <原因> | <验证入口> |

## 禁止依赖

| Forbidden ID | From | To | 禁止原因 | 替代路径 | 违反风险 |
|---|---|---|---|---|---|
| FD-01 | FEAT-02 | FEAT-01 | <原因> | <替代> | <风险> |

## 循环风险

| Cycle ID | 涉及对象 | 风险 | 当前处理 |
|---|---|---|---|
| CYCLE-01 | FEAT-01 / FEAT-02 | <风险> | eliminated / accepted / spike |
